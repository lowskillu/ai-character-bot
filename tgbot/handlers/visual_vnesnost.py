from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from tgbot.misc.customization_view import show_customization_menu
from tgbot.misc.localization import (
    APPEARANCE_HAIR_OPTIONS,
    APPEARANCE_SKIN_OPTIONS,
    APPEARANCE_STYLE_OPTIONS,
)
from tgbot.misc.screens import show_screen
from tgbot.misc.states import ProfileCustomizationState

visual_vnesnost_router = Router()

APPEARANCE_FIELDS_RU = [
    {"key": "hair", "title": "Волосы", "emoji": "💇"},
    {"key": "skin", "title": "Цвет кожи", "emoji": "🧬"},
    {"key": "style", "title": "Стиль", "emoji": "🎭"},
]
APPEARANCE_FIELDS_EN = [
    {"key": "hair", "title": "Hair", "emoji": "💇"},
    {"key": "skin", "title": "Skin tone", "emoji": "🧬"},
    {"key": "style", "title": "Style", "emoji": "🎭"},
]

# callback -> (profile_data key, localized options, ru prompt, en prompt).
# The three screens below were three near-identical handlers, and the save
# handler carried a fourth copy of each prompt — in Russian only.
#
# Keyed by the full callback, mirroring BODY_FIELDS in customization_body.py, so
# the decorator can register `F.data.in_(set(...))` and this dict stays the one
# source of truth. tests/routers/test_callback_coverage.py reads it directly.
APPEARANCE_FIELDS = {
    "appearance_hair": (
        "appearance_hair",
        APPEARANCE_HAIR_OPTIONS,
        "💇 Волосы\n\n"
        "Выбери цвет волос персонажа 🙂",
        "💇 Hair\n\n"
        "Choose the character's hair color 🙂",
    ),
    "appearance_skin": (
        "appearance_skin",
        APPEARANCE_SKIN_OPTIONS,
        "🧬 Цвет кожи\n\n"
        "Выбери цвет кожи персонажа 🙂",
        "🧬 Skin tone\n\n"
        "Choose the character's skin tone 🙂",
    ),
    "appearance_style": (
        "appearance_style",
        APPEARANCE_STYLE_OPTIONS,
        "🎭 Стиль\n\n"
        "Классика, минимализм или что-то необычное? Выбирай 🙂",
        "🎭 Style\n\n"
        "Classic, minimalist or something unusual? Your choice 🙂",
    ),
}


def get_appearance_main_keyboard(lang):
    fields = APPEARANCE_FIELDS_RU if lang == "ru" else APPEARANCE_FIELDS_EN
    rows = [
        [InlineKeyboardButton(text=f"{f['emoji']} {f['title']}", callback_data=f"appearance_{f['key']}")]
        for f in fields
    ]
    rows.append(
        [InlineKeyboardButton(text="🔙 Назад" if lang == "ru" else "🔙 Back", callback_data="appearance_back")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_appearance_option_keyboard(options, selected=None, back_cb="customize_appearance", lang="ru"):
    """Render the option grid.

    The old signature took a ``saved`` flag and appended a "💾 Save" button
    when it was false — but all four call sites passed ``saved=True``, so the
    button was never rendered and ``handle_appearance_save`` was unreachable.
    That handler was also broken: it read the selection from top-level FSM data
    rather than from ``profile_data``, where every choice is actually stored, so
    it would have shown an empty selection had anyone reached it. Choosing an
    option already persists it, exactly like every other sub-menu in the wizard.
    """
    btns = []
    for text, value in options:
        display = text + " ✅" if selected == value else text
        btns.append(InlineKeyboardButton(text=display, callback_data=f"appearance_choose_{value}"))

    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    rows.append([InlineKeyboardButton(text="🔙 Назад" if lang == "ru" else "🔙 Back", callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@visual_vnesnost_router.callback_query(
    F.data == "customize_appearance", StateFilter(None, ProfileCustomizationState.customizing)
)
async def handle_customize_appearance(call: CallbackQuery, state: FSMContext):
    lang = (await state.get_data()).get("language", "ru")
    text = (
        "💇 Внешность персонажа\n\n"
        "Выбери цвет волос, кожи и стиль — так, как тебе нравится 🙂"
        if lang == "ru" else
        "💇 Character appearance\n\n"
        "Pick the hair, skin tone and style you like 🙂"
    )
    await show_screen(call, text, get_appearance_main_keyboard(lang))


async def _show_appearance_options(call: CallbackQuery, state: FSMContext, field: str) -> None:
    key, options, text_ru, text_en = APPEARANCE_FIELDS[field]
    await state.update_data(current_appearance_field=field)
    data = await state.get_data()
    lang = data.get("language", "ru")
    # Read from profile_data, which is where every choice is actually stored.
    selected = data.get("profile_data", {}).get(key)
    await show_screen(
        call,
        text_ru if lang == "ru" else text_en,
        get_appearance_option_keyboard(options[lang], selected, lang=lang),
    )


@visual_vnesnost_router.callback_query(F.data.in_(set(APPEARANCE_FIELDS)))
async def handle_appearance_field(call: CallbackQuery, state: FSMContext):
    await _show_appearance_options(call, state, call.data)


@visual_vnesnost_router.callback_query(F.data.startswith("appearance_choose_"))
async def handle_appearance_choose(call: CallbackQuery, state: FSMContext):
    value = call.data[len("appearance_choose_"):]
    data = await state.get_data()
    field = data.get("current_appearance_field")
    if field not in APPEARANCE_FIELDS:
        # Still answer, or the button spins forever.
        await call.answer()
        return

    key, _options, _ru, _en = APPEARANCE_FIELDS[field]
    profile_data = data.get("profile_data", {})
    profile_data[key] = value
    await state.update_data(profile_data=profile_data)
    await _show_appearance_options(call, state, field)


@visual_vnesnost_router.callback_query(F.data == "appearance_back")
async def handle_appearance_back(call: CallbackQuery, state: FSMContext):
    await show_customization_menu(call, state)
