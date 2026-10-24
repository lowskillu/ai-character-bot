"""Concurrency limits and load shedding.

Without this the bot has no backpressure at all: every webhook update becomes an
unbounded asyncio task, and under overload they pile up until memory or the
connection pool gives out. Queueing without a bound turns overload into
unbounded latency — for a chat bot, a reply that lands four minutes late is
worse than an honest "try again", because the user has already closed the app.

Three layers, cheapest first:

1. per-user lock  — one in-flight request per user, so a spammer cannot burn
                    twenty LLM calls. Lives in Redis so it survives replicas.
2. per-service    — bounds concurrency against each downstream separately, with
   semaphore        a short acquire timeout that sheds instead of queueing.
3. global guard   — a backstop on total in-flight work.
"""

import asyncio
import contextlib
import logging
import os
from typing import AsyncIterator, Optional

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# Sized from the load test: at the target rate the LLM path needs roughly
# rate * median_latency concurrent slots. Raise LLM_CONCURRENCY together with
# the HTTP connector limit in tgbot/services/http.py — they cap each other.
LLM_CONCURRENCY = _env_int("LLM_CONCURRENCY", 256)
PROMPT_CONCURRENCY = _env_int("PROMPT_CONCURRENCY", 64)
IMAGE_CONCURRENCY = _env_int("IMAGE_CONCURRENCY", 8)
GLOBAL_INFLIGHT = _env_int("GLOBAL_INFLIGHT", 1000)

# How long to wait for a slot before giving up. Deliberately short: the point is
# to fail fast and tell the user, not to build a hidden queue.
ACQUIRE_TIMEOUT = float(os.getenv("ACQUIRE_TIMEOUT", "3"))

# Upper bound on how long one user's request may hold their lock.
USER_LOCK_TTL = _env_int("USER_LOCK_TTL", 180)


class Overloaded(Exception):
    """No capacity right now. Callers should tell the user and give up."""


class Busy(Exception):
    """This user already has a request in flight."""


_shed_counter = 0


def shed_count() -> int:
    """Number of requests rejected since start; surfaced by /metrics."""
    return _shed_counter


class Limits:
    """Holds the process-wide semaphores. One instance, built at startup."""

    def __init__(self) -> None:
        self.llm = asyncio.Semaphore(LLM_CONCURRENCY)
        self.prompt = asyncio.Semaphore(PROMPT_CONCURRENCY)
        self.image = asyncio.Semaphore(IMAGE_CONCURRENCY)
        self.global_inflight = asyncio.Semaphore(GLOBAL_INFLIGHT)

    @contextlib.asynccontextmanager
    async def guard(
        self, semaphore: asyncio.Semaphore, name: str, timeout: float = ACQUIRE_TIMEOUT
    ) -> AsyncIterator[None]:
        """Hold a slot, or raise Overloaded rather than queue indefinitely."""
        global _shed_counter
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=timeout)
        except asyncio.TimeoutError:
            _shed_counter += 1
            logger.warning("[limits] shedding: no %s slot within %ss", name, timeout)
            raise Overloaded(name) from None
        try:
            yield
        finally:
            semaphore.release()


@contextlib.asynccontextmanager
async def user_lock(
    redis, user_id: int, ttl: int = USER_LOCK_TTL
) -> AsyncIterator[None]:
    """One in-flight request per user.

    SET NX is a single atomic claim. Released in a finally so a crash mid-handler
    costs the user one TTL rather than locking them out forever.
    """
    key = f"busy:{user_id}"
    try:
        claimed = await redis.set(key, "1", ex=ttl, nx=True)
    except Exception as e:  # noqa: BLE001 — Redis down must not block the bot
        logger.error("[limits] user lock unavailable, proceeding: %s", e)
        yield
        return

    if not claimed:
        raise Busy(user_id)

    try:
        yield
    finally:
        with contextlib.suppress(Exception):
            await redis.delete(key)


# Process-wide instance. Safe to build at import time on 3.10+, where
# asyncio.Semaphore no longer binds to a loop on construction.
limits = Limits()


def overloaded_message(lang: Optional[str]) -> str:
    return (
        "Сейчас много запросов ⏳ Попробуй ещё раз через минуту."
        if (lang or "ru") != "en"
        else "Lots of requests right now ⏳ Please try again in a minute."
    )


def busy_message(lang: Optional[str]) -> str:
    return (
        "Секунду, я ещё печатаю… 💭"
        if (lang or "ru") != "en"
        else "Hold on, I'm still typing… 💭"
    )
