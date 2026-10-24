from aiogram import BaseMiddleware
from aiogram.types import Update
from typing import Callable, Dict, Any, Awaitable, Optional
import logging
import redis.asyncio as aioredis

# Was 3s, which is shorter than Telegram's webhook retry window — a retry
# arriving 5s later was processed a second time, producing a duplicate LLM call
# and a duplicate reply. 60s costs ~500 keys at 8 updates/s.
#
# Trade-off: if the process dies mid-handler the update stays claimed and the
# retry is dropped. Losing a message occasionally beats answering twice.
DEDUPE_TTL = 60


class AntiDuplicateMiddleware(BaseMiddleware):
    def __init__(self, redis: Optional[aioredis.Redis]):
        self.redis = redis
        self.logger = logging.getLogger(__name__)

    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any],
    ) -> Any:
        # No Redis: skip the check
        if not self.redis:
            return await handler(event, data)
            
        # Only raw updates are checked
        if not isinstance(event, Update):
            return await handler(event, data)
            
        update_id = getattr(event, "update_id", None)
        if update_id is None:
            return await handler(event, data)
            
        key = f"update:{update_id}"
        try:
            # SET NX is a single atomic claim. The previous GET-then-SET was a
            # TOCTOU race: two workers (or two replicas) could both read "not
            # seen" and both process the same update.
            claimed = await self.redis.set(key, "1", ex=DEDUPE_TTL, nx=True)
            if not claimed:
                self.logger.warning("[AntiDuplicate] duplicate update_id=%s skipped", update_id)
                return
        except Exception as e:
            self.logger.error(
                "[AntiDuplicate] Redis error (%s), processing update anyway: %s",
                type(e).__name__, e,
            )
        return await handler(event, data)
