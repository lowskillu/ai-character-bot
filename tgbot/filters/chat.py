"""Private-chat gate.

This filter existed but was never attached to anything, and fallback_router
matches every message — so adding the bot to a group turned it into a machine
that answered every message in that group, each one a paid LLM call. It is now
applied once at the dispatcher level in bot.py, which covers every router.
"""

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message, TelegramObject


class IsPrivate(BaseFilter):
    """True only for events originating in a one-to-one chat."""

    async def __call__(self, obj: TelegramObject) -> bool:
        if isinstance(obj, Message):
            return obj.chat.type == "private"
        if isinstance(obj, CallbackQuery):
            # An inline-mode callback carries no message at all; there is no
            # private chat behind it, so it does not belong here either.
            message = obj.message
            return message is not None and message.chat.type == "private"
        return True
