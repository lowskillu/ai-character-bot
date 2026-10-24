import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from tgbot.database.orm import AsyncORM
from tgbot.keyboards.profiles import get_new_user_keyboard, get_profiles_keyboard
from tgbot.misc.start_message_text import get_profiles_empty_text, get_profiles_exist_text
from tgbot.services.profile import get_user_profiles, is_premium

style_router = Router()
logger = logging.getLogger(__name__)

# show_style_choice() used to live here: ~12 lines that no router registered and
# nothing called. It also indexed STYLE_TEXT[lang] directly, so any user whose
# language column held something other than "ru"/"en" would have raised KeyError.
# The live style screen is menu.py's _show_style_screen.


@style_router.callback_query(F.data == "start_main")
async def start_main_style(call: CallbackQuery, state: FSMContext, user: dict = None):
    await state.clear()
    user_id = call.from_user.id
    lang = user.get("language", "ru") if user else "ru"

    # Read everything, then close the session *before* talking to Telegram. The
    # old version sent the reply from inside the `async with`, holding a pooled
    # connection across a Bot API round trip — the same shape that capped the
    # chat path until it was fixed.
    async with AsyncORM.users._get_session() as session:
        profiles = await get_user_profiles(session, user_id)
        premium = await is_premium(session, user_id)
        profile_buttons = [(p.id, p.name or "Без имени") for p in profiles]

    if profile_buttons:
        text = get_profiles_exist_text(lang)
        keyboard = get_profiles_keyboard(profile_buttons, premium, lang)
    else:
        text = get_profiles_empty_text(lang)
        keyboard = get_new_user_keyboard(lang)
    await call.message.answer(text, reply_markup=keyboard)
    await call.answer()
