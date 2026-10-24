"""Photo and message quotas, backed by Redis counters.

Lives here rather than in a handler because both the flows that spend quota and
the stats screen that displays it need the same numbers. They previously each
rebuilt the key format and the limits by hand, so the numbers had already
drifted apart.

Both quotas follow the same shape: free tier is a lifetime allowance with no
TTL, premium is a daily allowance that expires on its own.
"""

import logging
import os
from datetime import datetime
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


DEFAULT_LIMIT = _env_int("FREE_PHOTO_LIMIT", 2)  # free tier, lifetime
PREMIUM1_LIMIT = _env_int("PREMIUM_PHOTO_LIMIT", 50)  # premium tier, per day

# Advertised on the premium and stats screens as "25 messages, lifetime" and
# "200 messages per day". Until this existed nothing enforced either number: the
# free tier was effectively unlimited, and every message was a paid LLM call.
FREE_MESSAGE_LIMIT = _env_int("FREE_MESSAGE_LIMIT", 25)
PREMIUM_MESSAGE_LIMIT = _env_int("PREMIUM_MESSAGE_LIMIT", 200)

QUOTA_TTL = 60 * 60 * 25  # 25h, so a day boundary can never orphan a counter


def get_day_key() -> str:
    return datetime.utcnow().strftime("%Y%m%d")


def quota_key(user_id: int, premium_level: int) -> Tuple[str, int, Optional[int]]:
    """Return ``(redis key, limit, ttl)`` for this user's photo quota."""
    if premium_level >= 1:
        return (
            f"photo_limit:{user_id}:{premium_level}:{get_day_key()}",
            PREMIUM1_LIMIT,
            QUOTA_TTL,
        )
    return f"photo_limit:{user_id}:0", DEFAULT_LIMIT, None


def message_quota_key(user_id: int, premium_level: int) -> Tuple[str, int, Optional[int]]:
    """Return ``(redis key, limit, ttl)`` for this user's message quota."""
    if premium_level >= 1:
        return (
            f"msg_limit:{user_id}:{premium_level}:{get_day_key()}",
            PREMIUM_MESSAGE_LIMIT,
            QUOTA_TTL,
        )
    return f"msg_limit:{user_id}:0", FREE_MESSAGE_LIMIT, None


async def _try_consume(redis, key: str, limit: int, ttl: Optional[int]) -> bool:
    """Atomically reserve one slot. Returns False when over quota.

    The previous photo implementation read the counter, generated the image,
    then incremented — a read-then-act race that let concurrent requests sail
    past the limit. INCR reserves first; :func:`_release` hands the slot back
    when the work fails.
    """
    count = await redis.incr(key)
    if count == 1 and ttl is not None:
        await redis.expire(key, ttl)

    if count > limit:
        await redis.decr(key)
        return False
    return True


async def _release(redis, key: str, user_id: int) -> None:
    try:
        await redis.decr(key)
    except Exception as e:  # noqa: BLE001 — never fail a handler over this
        logger.warning("Failed to release quota %s for user %s: %s", key, user_id, e)


async def _usage(redis, key: str, limit: int) -> Tuple[int, int]:
    """``(used, limit)`` for display.

    Clamped at zero: a counter can only go negative through a release that was
    never reserved, and "-1/25 used" on the stats screen is a puzzle for
    the user rather than information.
    """
    used = int(await redis.get(key) or 0)
    return max(used, 0), limit


# --- photo ----------------------------------------------------------------

async def try_consume(redis, user_id: int, premium_level: int) -> bool:
    """Atomically reserve one photo slot. Returns False when over quota."""
    key, limit, ttl = quota_key(user_id, premium_level)
    return await _try_consume(redis, key, limit, ttl)


async def release(redis, user_id: int, premium_level: int) -> None:
    """Return a reserved photo slot after a failed generation."""
    key, _, _ = quota_key(user_id, premium_level)
    await _release(redis, key, user_id)


async def get_usage(redis, user_id: int, premium_level: int) -> Tuple[int, int]:
    """Return ``(used, limit)`` for display on the stats screen."""
    key, limit, _ = quota_key(user_id, premium_level)
    return await _usage(redis, key, limit)


# --- messages -------------------------------------------------------------

async def try_consume_message(redis, user_id: int, premium_level: int) -> bool:
    """Atomically reserve one message slot. Returns False when over quota."""
    key, limit, ttl = message_quota_key(user_id, premium_level)
    return await _try_consume(redis, key, limit, ttl)


async def release_message(redis, user_id: int, premium_level: int) -> None:
    """Return a reserved message slot when the reply never reached the user."""
    key, _, _ = message_quota_key(user_id, premium_level)
    await _release(redis, key, user_id)


async def get_message_usage(redis, user_id: int, premium_level: int) -> Tuple[int, int]:
    """Return ``(used, limit)`` for display on the stats screen.

    The stats screen used to count rows in ``profile_message_history``, which is
    trimmed to the last 10 per profile — so the number it showed could never
    grow past a handful and bore no relation to the advertised allowance.
    """
    key, limit, _ = message_quota_key(user_id, premium_level)
    return await _usage(redis, key, limit)


def quota_exhausted_message(lang: Optional[str], premium_level: int) -> str:
    """Text shown when a user runs out of messages."""
    ru = (lang or "ru") != "en"
    if premium_level >= 1:
        return (
            "Лимит сообщений на сегодня исчерпан 😔 Возвращайся завтра!"
            if ru else
            "You're out of messages for today 😔 Come back tomorrow!"
        )
    from tgbot.misc.branding import support_line

    lang = "ru" if ru else "en"
    head = "Лимит бесплатных сообщений исчерпан 😔" if ru else "You're out of free messages 😔"
    tail = support_line(lang, "Оформи премиум, чтобы продолжить общение", "Get premium to keep chatting")
    return f"{head}\n{tail}" if tail else head


async def reset_user_quotas(redis, user_id: int) -> None:
    """Reset all photo and message quota keys (free and premium) for a user in Redis."""
    if not redis:
        return
    day_key = get_day_key()
    keys_to_delete = [
        f"photo_limit:{user_id}:0",
        f"photo_limit:{user_id}:1:{day_key}",
        f"photo_limit:{user_id}:2:{day_key}",
        f"msg_limit:{user_id}:0",
        f"msg_limit:{user_id}:1:{day_key}",
        f"msg_limit:{user_id}:2:{day_key}",
    ]
    for key in keys_to_delete:
        try:
            await redis.delete(key)
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to delete quota key %s for user %s: %s", key, user_id, e)
