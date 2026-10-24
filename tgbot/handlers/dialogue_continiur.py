"""Switching between profiles: preview the last exchange, continue or restart.

Language used to come from the FSM (``state.get_data()["language"]``), which is
only populated by the customization wizard. Reached from /menu → Profiles the
state is empty, so every English user saw this screen in Russian. It now comes
from the ``user`` dict the DatabaseMiddleware injects, exactly like every other
handler, and falls back to the FSM only when that is missing.
"""

import logging
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import delete, desc, select

from tgbot.database.models import Profile, ProfileMessageHistory
from tgbot.database.orm import AsyncORM
from tgbot.services.dialog_history import get_profile_history_from_db
from tgbot.services.profile import set_active_profile

dialogue_router = Router()
logger = logging.getLogger(__name__)


async def _lang(state: FSMContext, user: dict | None) -> str:
    if user and user.get("language"):
        return user["language"]
    return (await state.get_data()).get("language", "ru")


def get_history_action_keyboard(lang: str = "ru", with_back: bool = True) -> InlineKeyboardMarkup:
    """Continue / restart / back. These labels were hard-coded in Russian."""
    if lang == "en":
        new_text, continue_text, back_text = "🔄 Start over", "➡️ Continue", "⬅️ Back"
    else:
        new_text, continue_text, back_text = "🔄 Начать новый", "➡️ Продолжить", "⬅️ Назад"

    rows = [
        [
            InlineKeyboardButton(text=new_text, callback_data="profile_history_new"),
            InlineKeyboardButton(text=continue_text, callback_data="profile_history_continue"),
        ]
    ]
    if with_back:
        rows.append(
            [InlineKeyboardButton(text=back_text, callback_data="profile_history_back")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _activate(call: CallbackQuery, redis, user_id: int, profile_id: int, lang: str) -> bool:
    """Point the user's active-profile pointer at this profile.

    Returns False when it could not be done. The active profile lives only in
    Redis, so without it the next message answers "Please select a profile first" —
    telling the user "Profile selected!" anyway, which both call sites used to do,
    is a straight lie about the state they are in.
    """
    if redis is None:
        logger.error("[dialogue] Redis was not injected; cannot set active profile")
        await call.answer(
            "Внутренняя ошибка. Попробуйте позже."
            if lang != "en" else
            "Internal error. Please try again later.",
            show_alert=True,
        )
        return False
    try:
        await set_active_profile(redis, user_id, profile_id)
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("[dialogue] could not set active profile for %s: %s", user_id, e)
        await call.answer(
            "Не удалось выбрать профиль. Попробуйте ещё раз."
            if lang != "en" else
            "Could not select the profile. Please try again.",
            show_alert=True,
        )
        return False


def _reunion_text(lang: str, name: str) -> str:
    return (
        f"✨ Ты снова общаешься с *{name}* 🙂"
        if lang != "en" else
        f"✨ You're chatting with *{name}* again 🙂"
    )


@dialogue_router.callback_query(F.data.regexp(r"^profile_select_(\d+)$"))
async def select_profile(
    call: CallbackQuery, state: FSMContext, user: dict = None, redis=None
):
    lang = await _lang(state, user)
    match = re.match(r"^profile_select_(\d+)$", call.data or "")
    if not match:
        await call.answer(
            "Ошибка выбора профиля" if lang != "en" else "Profile selection error",
            show_alert=True,
        )
        return
    profile_id = int(match.group(1))
    user_id = call.from_user.id

    # Ownership first, and only then make it active. profile_id comes straight
    # from callback data, which the user controls: activating before checking
    # let anyone point their own active-profile pointer at a stranger's id.
    # Nothing leaked — load_chat_context scopes by user_id too — but it left
    # them with a pointer that answers "Profile not found" to every message.
    #
    # One transaction for the ownership check, the preview and the timestamp;
    # the last of those used to open a second session inside the first.
    async with AsyncORM.users._get_session() as session:
        profile = (
            await session.execute(
                select(Profile).where(Profile.id == profile_id, Profile.user_id == user_id)
            )
        ).scalar_one_or_none()
        if profile is None:
            history, last_row, name = [], None, ""
        else:
            name = profile.name or ""
            history = await get_profile_history_from_db(session, user_id, profile_id)
            last_row = (
                await session.execute(
                    select(ProfileMessageHistory.created_at)
                    .where(
                        ProfileMessageHistory.user_id == user_id,
                        ProfileMessageHistory.profile_id == profile_id,
                    )
                    .order_by(desc(ProfileMessageHistory.created_at))
                    .limit(1)
                )
            ).first()

    if profile is None:
        logger.warning(
            "[dialogue] user %s selected profile %s that is not theirs", user_id, profile_id
        )
        await call.answer(
            "Profile not found" if lang != "en" else "Profile not found", show_alert=True
        )
        return

    if not await _activate(call, redis, user_id, profile_id, lang):
        return
    await state.update_data(active_profile_id=profile_id)

    if not history:
        await call.message.edit_text(
            _reunion_text(lang, name), reply_markup=None, parse_mode="Markdown"
        )
        await call.answer("Profile selected!" if lang != "en" else "Profile selected!")
        return

    preview_text = "\n".join(
        ("🫵 " if m["role"] == "user" else "💬 ") + m["text"] for m in history[-4:]
    )
    dt_text = ""
    if last_row:
        stamp = last_row[0].isoformat()[:19].replace("T", " ")
        dt_text = (
            f"\n\n🕒 Последний диалог: {stamp}"
            if lang != "en" else
            f"\n\n🕒 Last conversation: {stamp}"
        )

    msg_text = (
        (
            "У этого профиля есть история диалога.\n"
            "Вот последние 4 сообщения:\n\n" + preview_text + dt_text +
            "\n\nЧто будем делать?\n"
            "🔄 — Начать новый диалог (старый будет удалён)\n"
            "➡️ — Продолжить диалог с этого места.\n\n"
            "Выбери, как продолжить общение 💬"
        )
        if lang != "en" else
        (
            "This profile has a chat history.\n"
            "Here are the last 4 messages:\n\n" + preview_text + dt_text +
            "\n\nWhat would you like to do?\n"
            "🔄 — Start a new chat (the old one will be deleted)\n"
            "➡️ — Continue the old chat from this point.\n\n"
            "Choose how you want to continue 💬"
        )
    )
    await call.message.edit_text(msg_text, reply_markup=get_history_action_keyboard(lang))
    # Remember the chosen profile for the continue/restart buttons
    await state.update_data(_pending_profile_id=profile_id, _pending_profile_name=name)
    await call.answer()


@dialogue_router.callback_query(F.data.in_(["profile_history_new", "profile_history_continue"]))
async def profile_history_action_handler(
    call: CallbackQuery, state: FSMContext, user: dict = None, redis=None
):
    lang = await _lang(state, user)
    data = await state.get_data()
    profile_id = data.get("_pending_profile_id")
    profile_name = data.get("_pending_profile_name", "")
    user_id = call.from_user.id

    if not profile_id:
        await call.answer(
            "Ошибка: профиль не выбран." if lang != "en" else "Error: profile not selected.",
            show_alert=True,
        )
        return

    if call.data == "profile_history_new":
        # Clear the stored history
        async with AsyncORM.users._get_session() as session:
            await session.execute(
                delete(ProfileMessageHistory).where(
                    ProfileMessageHistory.user_id == user_id,
                    ProfileMessageHistory.profile_id == profile_id,
                )
            )
            # No explicit commit: _get_session() already wraps the body in
            # session.begin(), which commits on exit. Committing here ended the
            # transaction early and the outer context then tried to commit a
            # finished one.

    # The old version activated the profile only when a Redis client happened to
    # be injected, and returned from inside that branch — so the "continue" path
    # fell through to a second, duplicate reply whenever Redis was missing.
    if not await _activate(call, redis, user_id, profile_id, lang):
        return

    await call.message.edit_text(
        _reunion_text(lang, profile_name), reply_markup=None, parse_mode="Markdown"
    )
    await call.answer("Profile selected!" if lang != "en" else "Profile selected!")
    # Drop the temporary keys
    await state.update_data(_pending_profile_id=None, _pending_profile_name=None)


# Back button on the history screen
@dialogue_router.callback_query(F.data == "profile_history_back")
async def profile_history_back_handler(
    call: CallbackQuery, state: FSMContext, user: dict = None, redis=None
):
    # Leave the active profile alone; just go back to the profile list
    from tgbot.handlers.menu import show_profiles_menu

    await show_profiles_menu(call, state, user=user, redis=redis)


__all__ = ["select_profile", "profile_history_action_handler", "dialogue_router"]
