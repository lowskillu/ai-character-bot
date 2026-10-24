import logging
import re
from datetime import datetime

import aiogram.exceptions
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import select

from tgbot.database.models import Profile
from tgbot.database.orm import AsyncORM, session_context
from tgbot.keyboards.inline import get_ready_to_start_keyboard, get_style_keyboard
from tgbot.keyboards.menu import get_menu_keyboard, get_premium_back_button, get_reset_keyboard
from tgbot.keyboards.profiles import get_edit_profile_keyboard, get_profiles_menu_keyboard
from tgbot.middlewares.database import invalidate_user_cache
from tgbot.misc.branding import support_line
from tgbot.misc.screens import show_screen
from tgbot.misc.start_message_text import get_ready_to_start_text
from tgbot.misc.states import ProfileCustomizationState
from tgbot.services import premium, quotas
from tgbot.services.profile import (
    delete_all_profiles_for_user,
    get_active_profile,
    get_user_profiles,
    is_premium,
)
from tgbot.services.style import get_user_style, set_user_style

menu_router = Router()
logger = logging.getLogger(__name__)

EDIT_PROFILE_TEXT_RU = (
    "🎀 Какой профиль хочешь изменить?\n\n"
    "Выбери профиль, и мы откроем настройки ✏️"
)
EDIT_PROFILE_TEXT_EN = (
    "🎀 Which profile do you want to edit?\n\n"
    "Choose a profile and we'll open its settings ✏️"
)

def get_menu_text_and_keyboard(lang: str = "ru"):
    text = (
        "⚙️ Главное меню\nВыбери нужный раздел ниже"
        if lang == "ru" else
        "⚙️ Main menu\nChoose a section below"
    )
    return text, get_menu_keyboard(lang)

@menu_router.message(F.text == "/menu")
async def menu_handler(message: Message, state: FSMContext, user: dict = None):
    lang = user.get("language", "ru") if user else "ru"
    try:
        text, keyboard = get_menu_text_and_keyboard(lang)
        await message.answer(text, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"menu_handler: failed to send menu for user_id={message.from_user.id}: {e}")

@menu_router.callback_query(F.data == "menu_language")
async def menu_language_handler(call: CallbackQuery, state: FSMContext, user: dict = None):
    # 1. Use user dict if available (like other handlers)
    if user and user.get("language"):
        lang = user["language"]
    else:
        user_id = call.from_user.id
        lang = None
        try:
            db_user = await AsyncORM.users.get(user_id)
            if db_user and hasattr(db_user, "language") and db_user.language:
                lang = db_user.language
        except Exception:
            lang = None
        if not lang:
            lang = (await state.get_data()).get("language", "ru")
    text = (
        "🔄 Смена языка\n\n"
        "Выбери язык общения 🌍"
        if lang == "ru" else
        "🔄 Change language\n\n"
        "Choose the language 🌍"
    )
    try:
        await call.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="Русский 🇷🇺", callback_data="choose_lang_ru"),
                        InlineKeyboardButton(text="English 🇬🇧", callback_data="choose_lang_en"),
                    ],
                    [
                        InlineKeyboardButton(text="🔙 Назад" if lang == "ru" else "🔙 Back", callback_data="back_to_menu"),
                    ],
                ]
            ),
        )
    except aiogram.exceptions.TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await call.answer()

@menu_router.callback_query(F.data.in_(["choose_lang_ru", "choose_lang_en"]))
async def confirm_language_change(call: CallbackQuery, state: FSMContext):
    new_lang = "ru" if call.data == "choose_lang_ru" else "en"
    # Always allow language change, even if the same as current
    warning = (
        "⚠️ Ты точно хочешь сменить язык?\n\n"
        "Все профили персонажей будут удалены, и всё начнётся с чистого листа.\n\n"
        "Если всё верно — нажми «✅ Подтвердить».\n"
        "Если нет — «🔙 Отмена»"
        if new_lang == "ru" else
        "⚠️ Are you sure you want to change the language?\n\n"
        "All character profiles will be deleted, and everything will start from scratch.\n\n"
        "If you're sure — press '✅ Confirm'.\n"
        "If you changed your mind — '🔙 Cancel'"
    )
    try:
        await call.message.edit_text(
            warning,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="🔙 Отмена" if new_lang == "ru" else "🔙 Cancel", callback_data="cancel_language_change"),
                        InlineKeyboardButton(text="✅ Подтвердить" if new_lang == "ru" else "✅ Confirm", callback_data=f"confirm_language_{new_lang}"),
                    ]
                ]
            ),
        )
    except aiogram.exceptions.TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await call.answer()

@menu_router.callback_query(F.data.in_(["confirm_language_ru", "confirm_language_en"]))
async def do_language_change(call: CallbackQuery, state: FSMContext, redis=None):
    new_lang = "ru" if call.data == "confirm_language_ru" else "en"
    user_id = call.from_user.id
    try:
        # 1. Удаляем профили в явной сессии
        async with AsyncORM.users._get_session() as session:
            await delete_all_profiles_for_user(session, user_id)
        # 2. Обновляем язык пользователя (метод сам откроет сессию)
        await AsyncORM.users.update(user_id, language=new_lang)
        await invalidate_user_cache(redis, user_id)
        await state.update_data(language=new_lang)
        await show_screen(
            call,
            get_ready_to_start_text(new_lang),
            get_ready_to_start_keyboard(new_lang),
        )
    except Exception as e:
        logger.error(f"do_language_change: failed to change language for user_id={user_id}: {e}")
        await call.answer("Ошибка при смене языка." if new_lang == "ru" else "Error changing language.", show_alert=True)

# One handler for every "return to the main menu" button. These were four
# separate handlers with byte-identical bodies; two of them defaulted the
# language to "ru" and two to "en", which only differed for users whose
# language column is NULL. "ru" wins, matching the model default.
@menu_router.callback_query(
    F.data.in_({
        "cancel_language_change",
        "back_to_menu",
        "premium_back",
        "style_back",
        "reset_cancel",
    })
)
async def back_to_main_menu_handler(call: CallbackQuery, state: FSMContext, user: dict = None):
    lang = user.get("language", "ru") if user else "ru"
    text, keyboard = get_menu_text_and_keyboard(lang)
    await show_screen(call, text, keyboard)


@menu_router.callback_query(F.data == "menu_profiles")
async def show_profiles_menu(call: CallbackQuery, state: FSMContext, user: dict = None, redis=None):
    user = user or {}
    user_id = call.from_user.id
    lang = user.get("language", "ru")
    async with AsyncORM.users._get_session() as session:
        profiles = await get_user_profiles(session, user_id)
        premium = await is_premium(session, user_id)
        profile_buttons = [(p.id, p.name) for p in profiles]
    active_profile_id = None
    if redis:
        active_profile_id = await get_active_profile(redis, user_id)
    text = (
        "🧑‍🤝‍🧑 Твои персонажи\n"
        "С кем хочешь продолжить сегодня?\n"
        "Выбери профиль или создай новый 🙂"
    ) if lang == "ru" else (
        "🧑‍🤝‍🧑 Your characters\n"
        "Who do you want to continue with today?\n"
        "Pick a profile or create a new one 🙂"
    )
    keyboard = get_profiles_menu_keyboard(profile_buttons, active_profile_id, premium, lang)
    try:
        await call.message.edit_text(text, reply_markup=keyboard)
    except aiogram.exceptions.TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await call.answer()

@menu_router.callback_query(F.data == "menu_back_to_dialog")
async def back_to_main_menu(call: CallbackQuery, state: FSMContext, user: dict = None, redis=None):
    user_id = call.from_user.id
    lang = user.get("language", "ru") if user else "ru"

    # Получаем активный профиль
    active_profile_id = None
    try:
        # ConfigMiddleware always injects the shared client. The old fallback
        # here built a brand-new Redis client and pool and never closed it.
        if redis is None:
            logger.error("[menu_back_to_dialog] Redis was not injected")
        else:
            active_profile_id = await get_active_profile(redis, user_id)
    except Exception as e:
        logger.error(f"[menu_back_to_dialog] Ошибка получения активного профиля: {e}")

    if active_profile_id:
        # Получаем имя профиля
        try:
            async with AsyncORM.users._get_session() as session:
                result = await session.execute(
                    select(Profile).where(Profile.id == active_profile_id, Profile.user_id == user_id)
                )
                profile = result.scalar_one_or_none()
                if profile:
                    name = profile.name
                    text = (
                        f"Снова разговор с **{name}** 🙂  \n"
                        "Можно продолжить с того места, где вы остановились."
                        if lang == "ru" else
                        f"You're back to your chat with **{name}** 🙂  \nYou can continue where you left off."
                    )
                    await call.message.delete()
                    await call.message.answer(text, parse_mode="Markdown")
                else:
                    logger.warning(f"[menu_back_to_dialog] Профиль не найден: user_id={user_id}, profile_id={active_profile_id}")
                    # Возврат в главное меню, если профиль не найден
                    text, keyboard = get_menu_text_and_keyboard(lang)
                    await call.message.delete()
                    await call.message.answer(text, reply_markup=keyboard)
        except Exception as e:
            logger.error(f"[menu_back_to_dialog] Ошибка при получении профиля: {e}")
            text, keyboard = get_menu_text_and_keyboard(lang)
            await call.message.delete()
            await call.message.answer(text, reply_markup=keyboard)
    else:
        # Нет активного профиля — возвращаем в главное меню
        text, keyboard = get_menu_text_and_keyboard(lang)
        await call.message.delete()
        await call.message.answer(text, reply_markup=keyboard)
    await call.answer()

async def _read_premium(user_id: int) -> tuple[int, object]:
    """``(effective level, expiry)`` — the level already has the expiry applied."""
    async with AsyncORM.users._get_session() as session:
        user_obj = await session.get(AsyncORM.users.model, user_id)
        return premium.effective_level(user_obj), getattr(user_obj, "premium_until", None)


def _premium_status(level: int, until, lang: str, verbose: bool) -> str:
    """Render the premium line.

    Both screens built this by hand, and both keyed off the raw premium_level
    column, so an expired subscriber was shown "✅ Активен … до <дата в прошлом>".
    `level` here is already expiry-adjusted, so an expired grant reads Inactive.
    """
    if level < 1:
        if verbose:
            return "❌ Неактивен" if lang == "ru" else "❌ Inactive"
        return "Неактивен" if lang == "ru" else "Inactive"

    if until is None:
        return (
            ("✅ Активен (Премиум %d), бессрочно" % level) if lang == "ru"
            else ("✅ Active (Premium %d), no end date" % level)
        ) if verbose else ("Активен" if lang == "ru" else "Active")

    stamp = until.strftime("%d.%m.%Y" if verbose else "%d.%m.%y") if isinstance(until, datetime) else until
    if verbose:
        return (
            f"✅ Активен (Премиум {level}) до {stamp}" if lang == "ru"
            else f"✅ Active (Premium {level}) until {stamp}"
        )
    return f"Активен до {stamp}" if lang == "ru" else f"Active until {stamp}"


@menu_router.callback_query(F.data == "menu_premium")
async def premium_menu_handler(call: CallbackQuery, state: FSMContext, user: dict = None):
    lang = user.get("language", "ru") if user else "ru"
    premium_level, premium_until = await _read_premium(call.from_user.id)
    premium_str = _premium_status(premium_level, premium_until, lang, verbose=False)
    # Read from the quota module rather than written out by hand, so the sales
    # copy cannot advertise numbers the code does not enforce.
    if lang == "ru":
        text = (
            "🌟 Премиум возможности\n\n"
            "💫 Бесплатная версия:\n"
            f"• {quotas.DEFAULT_LIMIT} фото/навсегда\n"
            f"• {quotas.FREE_MESSAGE_LIMIT} сообщений/навсегда\n"
            "• Медленная генерация\n\n"
            "💎 Премиум-1 уровня:\n"
            f"• {quotas.PREMIUM1_LIMIT} фото/день\n"
            f"• {quotas.PREMIUM_MESSAGE_LIMIT} сообщений/день\n"
            "• Приоритетная генерация\n\n"
            f"💎 Премиум статус: {premium_str}"
        )
    else:
        text = (
            "🌟 Premium Features\n\n"
            "💫 Free Version:\n"
            f"• {quotas.DEFAULT_LIMIT} photos/forever\n"
            f"• {quotas.FREE_MESSAGE_LIMIT} messages/forever\n"
            "• Slow generation\n\n"
            "💎 Premium-1 Level:\n"
            f"• {quotas.PREMIUM1_LIMIT} photos/day\n"
            f"• {quotas.PREMIUM_MESSAGE_LIMIT} messages/day\n"
            "• Priority generation\n\n"
            f"💎 Premium status: {premium_str}"
        )
    contact = support_line(lang, "Чтобы активировать премиум, напишите", "To activate premium, write to")
    if contact:
        text += "\n\n" + contact
    markup = InlineKeyboardMarkup(inline_keyboard=[[get_premium_back_button(lang)]])
    try:
        await call.message.edit_text(text, reply_markup=markup)
    except aiogram.exceptions.TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await call.answer()

# The style screen is rendered identically whether the user is opening it or
# has just picked a style; only the source of `style` differs.
def _style_screen_text(lang: str, style: str) -> str:
    if lang == "en":
        return (
            "🎨 Choose image style\n\n"
            "🌟 Anime Style\nBright colors and clean, detailed illustrations — like a frame from an anime 🎨\n\n"
            "🎭 Realistic Style\nPhotorealistic images with natural colors. Like a real photo! 📸\n\n"
            f"Current style: <b>{'Anime style' if style == 'anime' else 'Realistic style'}</b>"
        )
    return (
        "🎨 Выбери стиль изображений\n\n"
        "🌟 Аниме стиль\nЯркие цвета и аккуратные детализированные иллюстрации — как кадр из аниме 🎨\n\n"
        "🎭 Реалистичный стиль\nФотореалистичные изображения с естественными цветами. Как настоящая фотография! 📸\n\n"
        f"Текущий стиль: <b>{'Аниме стиль' if style == 'anime' else 'Реалистичный стиль'}</b>"
    )


async def _show_style_screen(call: CallbackQuery, lang: str, style: str) -> None:
    keyboard = get_style_keyboard(lang, style)
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(
            text="◀️ Back" if lang == "en" else "◀️ Назад", callback_data="style_back"
        )
    ])
    await show_screen(call, _style_screen_text(lang, style), keyboard, parse_mode="HTML")


@menu_router.callback_query(F.data == "menu_style")
async def menu_style_handler(call: CallbackQuery, state: FSMContext, user: dict = None):
    lang = user.get("language", "ru") if user else "ru"
    async with AsyncORM.transaction():
        style = await get_user_style(session_context.get(), call.from_user.id)
    await _show_style_screen(call, lang, style)


@menu_router.callback_query(F.data.in_(["style_anime", "style_realistic"]))
async def menu_style_set_handler(call: CallbackQuery, state: FSMContext, user: dict = None):
    lang = user.get("language", "ru") if user else "ru"
    style = "anime" if call.data == "style_anime" else "realistic"
    async with AsyncORM.transaction():
        await set_user_style(session_context.get(), call.from_user.id, style)
    await _show_style_screen(call, lang, style)


@menu_router.callback_query(F.data == "menu_reset")
async def menu_reset_handler(call: CallbackQuery, state: FSMContext, user: dict = None):
    lang = user.get("language", "ru") if user else "ru"
    text = (
        "⚠️ Начать всё с чистого листа?  \nВсе персонажи, язык и стиль картинок будут **удалены навсегда**.\n\nПродолжить?"
        if lang == "ru" else
        "⚠️ Start from scratch?  \nAll characters, language and picture style **will be deleted forever**.\n\nAre you sure?"
    )
    try:
        await call.message.edit_text(text, reply_markup=get_reset_keyboard(lang), parse_mode="Markdown")
    except aiogram.exceptions.TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await call.answer()

@menu_router.callback_query(F.data == "reset_confirm")
async def menu_reset_confirm_handler(call: CallbackQuery, state: FSMContext, user: dict = None, redis=None):
    user_id = call.from_user.id
    lang = user.get("language", "ru") if user else "ru"
    async with AsyncORM.transaction():
        session = session_context.get()
        # Удалить профили (Profile)
        await delete_all_profiles_for_user(session, user_id)
        # Удалить историю сообщений профиля
        await AsyncORM.profile_message_history.delete_all_by_user(user_id=user_id)
        # Сбросить язык, стиль, соглашение (но НЕ премиум)
        await AsyncORM.users.update(user_id, language=None, style="anime", is_agreement_accepted=None)
    await invalidate_user_cache(redis, user_id)
    text = (
        "🗑 Все данные удалены.  \nЧтобы начать заново, нажми /start"
        if lang == "ru" else
        "🗑 All data erased.  \nTo start over, press /start"
    )
    try:
        await call.message.edit_text(text)
    except aiogram.exceptions.TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await call.answer()

@menu_router.callback_query(F.data == "menu_stats")
async def menu_stats_handler(call: CallbackQuery, state: FSMContext, user: dict = None, redis=None):
    """
    Показывает статистику пользователя: премиум-статус, лимиты и использование фото/сообщений.
    """
    user_id = call.from_user.id
    lang = user.get("language", "ru") if user else "ru"
    if redis is None:
        logger.error("[menu_stats] Redis was not injected")
        await call.answer("Внутренняя ошибка. Попробуйте позже.", show_alert=True)
        return
    try:
        premium_level, premium_until = await _read_premium(user_id)
        premium_str = _premium_status(premium_level, premium_until, lang, verbose=True)
        # Фото: usage и лимит. Limits come from tgbot/services/quotas.py so this
        # screen cannot drift away from what the photo handler actually enforces.
        photo_used, photo_limit = await quotas.get_usage(redis, user_id, premium_level)
        # Both counters now come from the same Redis keys the handlers spend, so
        # this screen cannot drift away from what is actually enforced. Messages
        # used to be counted as rows in profile_message_history, which is trimmed
        # to the last 10 per profile — the number could never reach the limit.
        msg_count, msg_limit = await quotas.get_message_usage(redis, user_id, premium_level)
        if premium_level >= 1:
            photo_str = f"{photo_used}/{photo_limit} использовано (сегодня)" if lang == "ru" else f"{photo_used}/{photo_limit} used today"
            msg_str = f"{msg_count}/{msg_limit} использовано (сегодня)" if lang == "ru" else f"{msg_count}/{msg_limit} used today"
        else:
            photo_str = f"{photo_used}/{photo_limit} использовано (навсегда)" if lang == "ru" else f"{photo_used}/{photo_limit} used (forever)"
            msg_str = f"{msg_count}/{msg_limit} использовано (навсегда)" if lang == "ru" else f"{msg_count}/{msg_limit} used (forever)"
        # Текст статистики
        if lang == "ru":
            text = (
                "📊 Статистика\n\n"
                f"💎 Премиум статус: {premium_str}\n"
                f"📸 Фото: {photo_str}\n"
                f"💬 Сообщения: {msg_str}"
            )
        else:
            text = (
                "📊 Statistics\n\n"
                f"💎 Premium status: {premium_str}\n"
                f"📸 Photos: {photo_str}\n"
                f"💬 Messages: {msg_str}"
            )
        contact = support_line(lang, "Для покупки премиума напишите", "To buy premium, write to")
        if contact:
            text += "\n\n" + contact
        # Кнопка назад
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад" if lang == "ru" else "🔙 Back", callback_data="back_to_menu")],
            ]
        )
        try:
            await call.message.edit_text(text, reply_markup=markup)
        except aiogram.exceptions.TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                raise
        await call.answer()
    except Exception as e:
        logger.error(f"menu_stats_handler: Ошибка при получении статистики для user_id={user_id}: {e}")
        await call.answer("Ошибка при получении статистики." if lang == "ru" else "Error getting statistics.", show_alert=True)

@menu_router.callback_query(F.data == "edit_profile")
async def edit_profile_menu(call: CallbackQuery, state: FSMContext, user: dict = None):
    lang = user.get("language", "ru") if user else "ru"
    text = EDIT_PROFILE_TEXT_RU if lang == "ru" else EDIT_PROFILE_TEXT_EN
    user_id = call.from_user.id
    async with AsyncORM.users._get_session() as session:
        profiles = await get_user_profiles(session, user_id)
        profile_buttons = [(p.id, p.name) for p in profiles]
    keyboard = get_edit_profile_keyboard(profile_buttons, lang)
    try:
        await call.message.edit_text(text, reply_markup=keyboard)
    except aiogram.exceptions.TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await call.answer()

# Обработчик выбора профиля для редактирования
@menu_router.callback_query(F.data.regexp(r"^edit_profile_select_(\d+)$"))
async def start_edit_profile(call: CallbackQuery, state: FSMContext, user: dict = None):
    match = re.match(r"^edit_profile_select_(\d+)$", call.data or "")
    if not match:
        await call.answer("Ошибка выбора профиля", show_alert=True)
        return
    profile_id = int(match.group(1))
    await state.update_data(editing_profile_id=profile_id)
    # Запускаем кастомизацию через кастомный state
    await state.set_state(ProfileCustomizationState.customizing)
    # Передаём управление кастомизации (пусть кастомизация сама заберёт editing_profile_id из state)
    from tgbot.handlers.customization import start_profile_customization
    await start_profile_customization(call, state, user)
    await call.answer() 