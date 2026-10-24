"""Runware image-generation client.

The SDK keeps a persistent websocket, so the connection is shared process-wide.
Two problems with the previous version:

* creation was unguarded — concurrent first calls each constructed a ``Runware``
  and called ``connect()``, leaving orphaned sockets;
* there was no reconnect, so once the websocket dropped every subsequent
  request failed until the process was restarted.
"""

import asyncio
import logging
import os
from typing import Optional

from runware import IImageInference, ILora, ISafety, Runware

logger = logging.getLogger(__name__)

# Concurrency is NOT capped here. It used to be, with a private
# `asyncio.Semaphore(8)` — and once the caller started holding
# `limits.guard(limits.image)` as well, the two stacked: the outer one sheds
# after ACQUIRE_TIMEOUT, the inner one queues forever, and the effective ceiling
# was min(IMAGE_CONCURRENCY, 8) no matter what IMAGE_CONCURRENCY was set to.
# Raising the env var silently did nothing.
#
# One ceiling, in tgbot/services/limits.py, where it is env-configurable and
# sheds instead of queueing.
DEFAULT_TIMEOUT = int(os.getenv("RUNWARE_TIMEOUT", "60"))

# Model ids were inline in handlers/photo.py as a one-line conditional, so
# switching a checkpoint — the main quality lever on this path — meant editing a
# handler and rebuilding the image.
MODEL_REALISTIC = os.getenv("IMAGE_MODEL_REALISTIC", "runware:101@1")
MODEL_ANIME = os.getenv("IMAGE_MODEL_ANIME", "runware:101@1")

# Generation parameters. 1024x1024 at 20 steps is what the bot has always sent.
IMAGE_WIDTH = int(os.getenv("IMAGE_WIDTH", "1024"))
IMAGE_HEIGHT = int(os.getenv("IMAGE_HEIGHT", "1024"))
IMAGE_STEPS = int(os.getenv("IMAGE_STEPS", "20"))
IMAGE_CFG_SCALE = float(os.getenv("IMAGE_CFG_SCALE", "7.5"))

# Sent with every image request: Runware checks the result and marks an image
# that fails. ``content_check()`` builds it; ``_failed_content_check()`` reads it.
def content_check() -> ISafety:
    return ISafety(checkContent=True)


# Result field the SDK sets on an image that failed the check
# (see runware.types.IImage).
_CHECK_FLAG_FIELD = "NSFWContent"


def _failed_content_check(image) -> bool:
    return getattr(image, _CHECK_FLAG_FIELD, None) is True


_sdk: Optional[Runware] = None
_lock = asyncio.Lock()


def parse_loras_from_env(prefix: str) -> list[ILora]:
    """Parse up to 4 LoRAs from environment variables with given prefix."""
    loras: list[ILora] = []
    for i in range(1, 5):
        model_key = f"{prefix}{i}"
        weight_key = f"{prefix}{i}_WEIGHT"
        model_str = os.getenv(model_key, "").strip()
        if model_str:
            try:
                weight = float(os.getenv(weight_key, "0.8").strip())
            except ValueError:
                weight = 0.8
            loras.append(ILora(model=model_str, weight=weight))
    return loras


def model_for_style(style: Optional[str]) -> str:
    """Checkpoint for a profile style.

    Anything unrecognised falls back to anime, matching what the inline
    conditional in photo.py did.
    """
    return MODEL_REALISTIC if (style or "").lower() == "realistic" else MODEL_ANIME


def loras_for_style(style: Optional[str]) -> list[ILora]:
    """Return configured LoRAs for realistic or anime style."""
    if (style or "").lower() == "realistic":
        return parse_loras_from_env("IMAGE_REALISTIC_LORA_")
    return parse_loras_from_env("IMAGE_ANIME_LORA_")


async def get_runware_sdk() -> Runware:
    """Return the shared, connected SDK instance, creating it if needed."""
    global _sdk

    if _sdk is not None:
        return _sdk

    async with _lock:
        # Re-check: another task may have connected while we waited.
        if _sdk is not None:
            return _sdk

        api_key = os.getenv("RUNWARE_API_KEY")
        if not api_key:
            raise RuntimeError("RUNWARE_API_KEY is not set")

        sdk = Runware(api_key=api_key)
        await sdk.connect()
        _sdk = sdk
        logger.info("Connected to Runware")
        return _sdk


async def _reset_sdk() -> None:
    """Drop the cached client so the next call reconnects."""
    global _sdk

    async with _lock:
        stale, _sdk = _sdk, None

    if stale is not None:
        logger.warning("Dropping Runware connection; it will be re-established on next use")
        disconnect = getattr(stale, "disconnect", None)
        if disconnect is not None:
            try:
                await disconnect()
            except Exception as e:  # noqa: BLE001 — best effort teardown
                logger.debug("Runware disconnect failed: %s", e)


async def async_runware_request(
    user_id: int,
    request_image: IImageInference,
    timeout: int = DEFAULT_TIMEOUT,
    reference_photo_url: Optional[str] = None,
) -> Optional[str]:
    """Generate one image and return its URL, or None on failure.

    Retries once on connection failure, because the most common error is a
    websocket that died while idle. The caller is responsible for holding a
    concurrency slot — see the note at the top of this module.
    """
    # Pure Text-to-Image using detailed profile prompt yields non-distorted, crisp photos

    for attempt in (1, 2):
        try:
            sdk = await get_runware_sdk()
            images = await asyncio.wait_for(
                sdk.imageInference(requestImage=request_image), timeout=timeout
            )
        except asyncio.TimeoutError:
            logger.error("[runware] timeout for user_id=%s (attempt %s)", user_id, attempt)
            await _reset_sdk()
            if attempt == 1:
                continue
            return None
        except Exception as e:  # noqa: BLE001 — SDK raises assorted socket errors
            err_msg = str(e)
            if request_image.referenceImages and ("unsupportedParameter" in err_msg or "referenceImages" in err_msg):
                logger.warning(
                    "[runware] model %s does not support referenceImages for user_id=%s, retrying without referenceImages",
                    request_image.model, user_id
                )
                request_image.referenceImages = None
                continue

            logger.error(
                "[runware] error for user_id=%s (attempt %s): %s", user_id, attempt, e
            )
            await _reset_sdk()
            if attempt == 1:
                continue
            return None

        # Every request asks Runware to run its content check; an image that
        # fails it is never delivered, whatever the prompt said.
        if images and _failed_content_check(images[0]):
            logger.warning("[runware] flagged image discarded for user_id=%s", user_id)
            return None

        if images and getattr(images[0], "imageURL", None):
            logger.info("[runware] generated image for user_id=%s", user_id)
            return images[0].imageURL

        logger.error("[runware] no imageURL returned for user_id=%s", user_id)
        return None

    return None
