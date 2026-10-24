from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
import logging

from tgbot.misc.customization_view import show_customization_menu
from tgbot.misc.screens import show_screen
from tgbot.misc.localization import BODY_TYPE_OPTIONS, HEIGHT_OPTIONS

logger = logging.getLogger(__name__)
customization_body_router = Router()


def get_body_main_keyboard(lang="ru"):
    """Создает главную клавиатуру для настройки телосложения"""
    if lang == "ru":
        rows = [
    [InlineKeyboardButton(text="📐 Телосложение", callback_data="body_type")],
    [InlineKeyboardButton(text="📏 Рост", callback_data="body_height")],
    [InlineKeyboardButton(text="🔙 Назад", callback_data="body_back")],
        ]
    else:
        rows = [
            [InlineKeyboardButton(text="📐 Body Type", callback_data="body_type")],
            [InlineKeyboardButton(text="📏 Height", callback_data="body_height")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="body_back")],
        ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

def get_body_option_keyboard(options, selected=None, lang="ru"):
    """Универсальная функция для создания клавиатуры выбора телосложения и роста"""
    rows = []
    for text, value in options:
        display = text
        if selected == value:
            display += " ✅"
        rows.append([InlineKeyboardButton(text=display, callback_data=f"body_choose_{value}")])
    
    rows.append([InlineKeyboardButton(text="🔙 Назад" if lang == "ru" else "🔙 Back", callback_data="body_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@customization_body_router.callback_query(F.data == "customize_body")
async def handle_customize_body(call: CallbackQuery, state: FSMContext): 
    """Главное меню настройки телосложения"""
    lang = (await state.get_data()).get("language", "ru")
    text = (
        "📐 Телосложение персонажа\n\n"
        "Выберите тип телосложения и рост персонажа."
        if lang == "ru" else
        "📐 Character build\n\n"
        "Choose the character's build and height."
    )
    
    keyboard = get_body_main_keyboard(lang)
    if hasattr(call.message, 'edit_text') and call.message is not None:
        await call.message.edit_text(text, reply_markup=keyboard)
    else:
        await call.message.answer(text, reply_markup=keyboard)
    await call.answer()

# callback -> (profile_data key, localized option table, ru prompt, en prompt).
# These screens were separate handlers measured 93-97% identical to one
# another. The prompts were also Russian-only regardless of language; the
# English side is filled in here.
BODY_FIELDS = {
    "body_type": (
        "body_type", BODY_TYPE_OPTIONS,
        "Выберите тип телосложения.", "Choose the body type.",
    ),
    "body_height": (
        "body_height", HEIGHT_OPTIONS,
        "Укажите рост персонажа.", "Choose the character's height.",
    ),
}


async def _show_body_options(call: CallbackQuery, state: FSMContext, field: str) -> None:
    key, options, text_ru, text_en = BODY_FIELDS[field]
    data = await state.get_data()
    lang = data.get("language", "ru")
    selected = data.get("profile_data", {}).get(key)
    await show_screen(
        call,
        text_ru if lang == "ru" else text_en,
        get_body_option_keyboard(options[lang], selected, lang),
    )


@customization_body_router.callback_query(F.data.in_(set(BODY_FIELDS)))
async def handle_body_field(call: CallbackQuery, state: FSMContext):
    """Показывает выбор для одного параметра телосложения."""
    await _show_body_options(call, state, call.data)


@customization_body_router.callback_query(F.data.startswith("body_choose_"))
async def handle_body_choose(call: CallbackQuery, state: FSMContext):
    """Обработка выбора параметра телосложения.

    Reads the FSM state once. The previous version awaited state.get_data()
    six times for a single button press, each one a Redis round trip.
    """
    value = call.data[len("body_choose_"):]
    data = await state.get_data()
    lang = data.get("language", "ru")
    profile_data = data.get("profile_data", {})

    for field, (key, options, _ru, _en) in BODY_FIELDS.items():
        if value in [v for _, v in options[lang]]:
            profile_data[key] = value
            await state.update_data(profile_data=profile_data)
            await _show_body_options(call, state, field)
            return

    # Unknown value: still answer, or the button spins forever.
    await call.answer()


@customization_body_router.callback_query(F.data == "body_main")
async def handle_body_main(call: CallbackQuery, state: FSMContext):
    """Возврат к главному меню телосложения"""
    await handle_customize_body(call, state)

@customization_body_router.callback_query(F.data == "body_back")
async def handle_body_back(call: CallbackQuery, state: FSMContext):
    """Возврат к главному меню кастомизации"""
    await show_customization_menu(call, state)
