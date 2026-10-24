"""Maintenance gate: when IN_DEVELOPMENT is on, only admins may use the bot.

Both branches of the old version called the handler, so the middleware did
nothing at all — the bot was fully open no matter how IN_DEVELOPMENT was set.
"""

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from tgbot.config import Config

logger = logging.getLogger(__name__)

MAINTENANCE_TEXT = {
    "ru": "🛠 Бот на техобслуживании. Загляни чуть позже!",
    "en": "🛠 The bot is under maintenance. Please check back soon!",
}


class DeveloperMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any],
    ) -> Any:
        if not event.from_user:
            return await handler(event, data)

        config: Config = data["config"]
        if not config.misc.dev or event.from_user.id in config.tg_bot.admin_ids:
            return await handler(event, data)

        # Blocked. Say so rather than dropping the update silently: a user who
        # gets no reply cannot tell whether to wait or retry, and retries add
        # load exactly when there is none to spare.
        user = data.get("user") or {}
        text = MAINTENANCE_TEXT.get(user.get("language") or "ru", MAINTENANCE_TEXT["ru"])
        logger.debug("[dev] blocked non-admin %s in development mode", event.from_user.id)
        try:
            if isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
            else:
                await event.answer(text)
        except Exception as e:  # noqa: BLE001 — never fail an update over this
            logger.warning("[dev] could not notify blocked user: %s", e)
        return None
