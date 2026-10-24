import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from tgbot.config import Config
from tgbot.database.orm import AsyncORM
from tgbot.middlewares.database import invalidate_user_cache
from tgbot.services.premium import AmbiguousUsername, grant_premium

premium_router = Router()
logger = logging.getLogger(__name__)

# The admin list comes from the Config that ConfigMiddleware injects. This
# module used to call load_config() at import time, which read .env a second
# time and made importing the handler package fail without a full environment.
#
# The check stays inside the handler rather than becoming a router-level
# AdminFilter on purpose: a filtered-out /addpremium would fall through to
# user_router's free-text handler and be sent to the LLM as chat.


@premium_router.message(Command("addpremium"))
async def add_premium_handler(message: Message, config: Config = None, redis=None, **data):
    """
    /addpremium <level> <username|id> <days>
    Admins only (ids come from ADMINS in .env).
    """
    admin_ids = set(config.tg_bot.admin_ids) if config else set()
    if message.from_user.id not in admin_ids:
        await message.answer("⛔️ Access denied.")
        return

    args = (message.text or "").split()
    if len(args) != 4:
        await message.answer(
            "Usage: /addpremium <level> <username|id> <days>"
        )
        return

    _, level_raw, identifier, days_raw = args
    try:
        level = int(level_raw)
        days = int(days_raw)
    except ValueError:
        await message.answer("Level and days must be numbers.")
        return

    try:
        # One transaction, and it returns the user — the old version granted,
        # then ran a second query to find the same row again for the notice.
        async with AsyncORM.users._get_session() as session:
            user = await grant_premium(session, identifier, level, days)
            granted_id = user.id if user else None
            granted_lang = (getattr(user, "language", None) or "ru") if user else "ru"
    except AmbiguousUsername as e:
        # Usernames are not unique any more (Telegram reassigns them), so say
        # which rows collided and let the admin pick one by id.
        await message.answer(
            f"@{e.username} belongs to several users: {e.user_ids}\n"
            f"Repeat with an id: /addpremium {level} <id> {days}"
        )
        return
    except Exception as e:  # noqa: BLE001
        logger.exception("addpremium failed: %s", e)
        await message.answer("Could not process the command.")
        return

    if granted_id is None:
        await message.answer(f"User {identifier} not found.")
        return

    await message.answer(f"Premium {level} granted to {identifier} for {days} days ✅")

    # The cached user row carries premium_level, and the chat quota check reads
    # it. Without this the grant would not take effect for up to one cache TTL —
    # the user keeps seeing "out of messages" after paying.
    await invalidate_user_cache(redis, granted_id)
    try:
        await message.bot.send_message(
            granted_id,
            f"Вам выдан премиум {level} на {days} дней! Поздравляем! 🎉"
            if granted_lang == "ru" else
            f"You have been granted premium {level} for {days} days! 🎉",
        )
    except Exception as e:  # noqa: BLE001 — a blocked user must not fail the grant
        logger.warning("could not notify user %s: %s", identifier, e)
