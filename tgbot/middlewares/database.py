"""Resolve the acting user for every update.

This runs on *every* message and callback, so it was the single most frequent
database query in the bot: at 96 updates/s the breakpoint ramp showed the pool
climbing to 18 of 20 connections, and a third of that traffic was this
middleware re-reading a row that almost never changes.

The row is now cached in Redis. Each cached hit removes one BEGIN / SELECT /
COMMIT round trip from the critical path.
"""

import json
import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

from tgbot.database.orm import AsyncORM
from tgbot.services import premium

logger = logging.getLogger(__name__)

# Short on purpose. Everything that edits these fields invalidates the key
# explicitly, so the TTL is only a backstop against a missed invalidation --
# it bounds how long a stale language could linger, not how it is normally
# refreshed.
CACHE_TTL = 60


def _cache_key(user_id: int) -> str:
    return f"user:{user_id}"


async def invalidate_user_cache(redis, user_id: int) -> None:
    """Drop the cached row. Call after any write to a cached field."""
    if redis is None:
        return
    try:
        await redis.delete(_cache_key(user_id))
    except Exception as e:  # noqa: BLE001 — a cache miss is harmless
        logger.warning("[user-cache] invalidate failed for %s: %s", user_id, e)


class DatabaseMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any],
    ) -> Any:
        if not event.from_user:
            return await handler(event, data)

        redis = data.get("redis")
        user_id = event.from_user.id
        username = event.from_user.username

        cached = await self._read_cache(redis, user_id)
        # A changed username still has to reach the database, so only serve
        # from cache when it matches what Telegram just told us.
        if cached is not None and cached.get("username") == username:
            data["user"] = cached
            return await handler(event, data)

        try:
            data["user"] = await self._load_from_db(user_id, username)
        except Exception as e:  # noqa: BLE001
            # A pool timeout here used to abort the update before any handler
            # ran, so the user got no message at all. Handlers already cope with
            # user=None (they fall back to Russian), and an error reply beats
            # silence.
            logger.error("[user-cache] db load failed for %s: %s", user_id, e)
            data["user"] = None
            return await handler(event, data)

        await self._write_cache(redis, user_id, data["user"])
        return await handler(event, data)

    @staticmethod
    async def _read_cache(redis, user_id: int) -> Optional[dict]:
        if redis is None:
            return None
        try:
            raw = await redis.get(_cache_key(user_id))
        except Exception as e:  # noqa: BLE001 — Redis down must not break the bot
            logger.warning("[user-cache] read failed for %s: %s", user_id, e)
            return None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return None

    @staticmethod
    async def _write_cache(redis, user_id: int, user: Optional[dict]) -> None:
        if redis is None or user is None:
            return
        try:
            # registered_at is a datetime and is not in the payload below, so
            # the dict stays JSON-serialisable.
            await redis.set(_cache_key(user_id), json.dumps(user), ex=CACHE_TTL)
        except Exception as e:  # noqa: BLE001
            logger.warning("[user-cache] write failed for %s: %s", user_id, e)

    @staticmethod
    async def _load_from_db(user_id: int, username: Optional[str]) -> Optional[dict]:
        async with AsyncORM.users._get_session() as session:
            user_obj = await session.get(AsyncORM.users.model, user_id)
            if not user_obj:
                user_obj = await AsyncORM.users.create(id=user_id, username=username)
            elif username != user_obj.username:
                user_obj = await AsyncORM.users.update(user_obj.id, username=username)

            if not user_obj:
                return None
            return {
                "id": user_obj.id,
                "username": user_obj.username,
                "language": getattr(user_obj, "language", "ru"),
                "is_agreement_accepted": getattr(user_obj, "is_agreement_accepted", False),
                # Carried on the cached row so the quota check on the chat hot
                # path costs no extra query. Expiry is already applied, so worst
                # case a lapsed user keeps premium for one CACHE_TTL. Anything
                # that grants or revokes premium must call invalidate_user_cache().
                "premium_level": premium.effective_level(user_obj),
            }
