"""Last-resort handler for messages nothing else claimed.

Must stay last in ``routers_list``. It previously lived in user.py as a bare
``@user_router.message()``; because user_router is registered before
customization_router, it swallowed the profile-creation wizard's text input and
answered every such message with "use the buttons to delete a profile".
"""

import logging

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

fallback_router = Router()
logger = logging.getLogger(__name__)


@fallback_router.message()
async def handle_unmatched_message(message: Message, state: FSMContext, user: dict = None):
    lang = user.get("language", "ru") if user else "ru"
    current_state = await state.get_state()
    logger.debug(
        "[fallback] unmatched message from user %s in state %s",
        message.from_user.id if message.from_user else None,
        current_state,
    )
    await message.answer(
        "Не понял тебя 🤔 Воспользуйся кнопками меню или напиши /menu."
        if lang == "ru"
        else "I didn't catch that 🤔 Use the menu buttons or send /menu."
    )
