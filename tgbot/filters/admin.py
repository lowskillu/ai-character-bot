from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from tgbot.config import Config


class AdminFilter(BaseFilter):
    is_admin: bool = True

    # Applied to both message and callback_query; both carry from_user.
    async def __call__(self, obj: Message | CallbackQuery, config: Config) -> bool:
        if not obj.from_user:
            return not self.is_admin
        return (obj.from_user.id in config.tg_bot.admin_ids) == self.is_admin
