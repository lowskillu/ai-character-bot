"""The four single-choice wizard screens: clothing, personality, location, role.

Each used to be its own module, and the four were structurally 86-92% identical
— the same open/choose/back trio differing only in a callback prefix, a
``profile_data`` key, one prompt and one option list. Those four values are now
the table below, which is the same shape ``BODY_FIELDS`` and
``APPEARANCE_FIELDS`` already use inside their own modules.

Callback convention, unchanged: ``customize_<name>``, ``<name>_choose_<value>``,
``<name>_back``.
"""

from dataclasses import dataclass
from typing import Sequence, Tuple

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

from tgbot.keyboards.options import build_option_keyboard
from tgbot.misc.customization_view import show_customization_menu
from tgbot.misc.localization import (
    CLOTHING_OPTIONS_EN,
    CLOTHING_OPTIONS_RU,
    LOCATION_OPTIONS_LOCALIZED,
    PERSONALITY_OPTIONS_EN,
    PERSONALITY_OPTIONS_RU,
    ROLE_OPTIONS_LOCALIZED,
)
from tgbot.misc.screens import show_screen

customization_options_router = Router()

Options = Sequence[Tuple[str, str]]


@dataclass(frozen=True)
class OptionScreen:
    """One pick-one-value screen in the character wizard."""

    field: str  # key inside profile_data
    options: dict[str, Options]  # lang -> (label, value) pairs
    text_ru: str
    text_en: str

    def prompt(self, lang: str) -> str:
        return self.text_ru if lang == "ru" else self.text_en

    def keyboard(self, lang: str = "ru", selected=None) -> InlineKeyboardMarkup:
        return build_option_keyboard(
            self.options["ru" if lang == "ru" else "en"],
            choose_prefix=f"{self.field}_choose_",
            back_callback=f"{self.field}_back",
            lang=lang,
            selected=selected,
        )


SCREENS: dict[str, OptionScreen] = {
    "clothing": OptionScreen(
        field="clothing",
        options={"ru": CLOTHING_OPTIONS_RU, "en": CLOTHING_OPTIONS_EN},
        text_ru=(
            "👕 Во что одет персонаж?\n\n"
            "Выбери повседневный образ ✨"
        ),
        text_en=(
            "👕 What is the character wearing?\n\n"
            "Pick an everyday outfit ✨"
        ),
    ),
    "personality": OptionScreen(
        field="personality",
        options={"ru": PERSONALITY_OPTIONS_RU, "en": PERSONALITY_OPTIONS_EN},
        text_ru=(
            "🐱 Выбираем характер\n\n"
            "Спокойный и рассудительный? Весёлый и разговорчивый? Или уверенный в себе?\n"
            "Выбери характер собеседника 🙂"
        ),
        text_en=(
            "🐱 Let's choose the personality\n\n"
            "Calm and thoughtful? A cheerful chatterbox? Or confident?\n"
            "Pick what your conversation partner is like 🙂"
        ),
    ),
    "location": OptionScreen(
        field="location",
        options=LOCATION_OPTIONS_LOCALIZED,
        text_ru=(
            "🌇 Где будет проходить общение?\n\n"
            "Выбери место для ваших разговоров 🙂"
        ),
        text_en=(
            "🌇 Where does the conversation take place?\n\n"
            "Pick a place for your chats 🙂"
        ),
    ),
    "role": OptionScreen(
        field="role",
        options=ROLE_OPTIONS_LOCALIZED,
        text_ru=(
            "🎭 Роль персонажа\n\n"
            "Выбери, кем будет персонаж в ваших разговорах"
        ),
        text_en=(
            "🎭 Character role\n\n"
            "Pick who the character is in your conversations"
        ),
    ),
}

# Callback values the router answers, derived from the table so the two cannot
# drift. tests/routers/test_callback_coverage.py reads these directly.
OPEN_CALLBACKS = {f"customize_{name}" for name in SCREENS}
BACK_CALLBACKS = {f"{name}_back" for name in SCREENS}
CHOOSE_PREFIXES = tuple(f"{name}_choose_" for name in SCREENS)


async def _show(call: CallbackQuery, state: FSMContext, screen: OptionScreen, selected=None):
    lang = (await state.get_data()).get("language", "ru")
    await show_screen(call, screen.prompt(lang), screen.keyboard(lang, selected))


@customization_options_router.callback_query(F.data.in_(OPEN_CALLBACKS))
async def handle_open(call: CallbackQuery, state: FSMContext):
    """Open an option screen."""
    screen = SCREENS[call.data[len("customize_"):]]
    data = await state.get_data()
    await _show(call, state, screen, data.get("profile_data", {}).get(screen.field))


@customization_options_router.callback_query(
    F.data.func(lambda d: isinstance(d, str) and d.startswith(CHOOSE_PREFIXES))
)
async def handle_choose(call: CallbackQuery, state: FSMContext):
    """Store the choice and redraw the same screen."""
    name, sep, value = call.data.partition("_choose_")
    screen = SCREENS.get(name) if sep else None
    if screen is None:
        # The filter should make this unreachable, but partition is string
        # surgery: a future option value containing "_choose_" would land here.
        # Answer anyway, or the button spins forever.
        await call.answer()
        return

    data = await state.get_data()
    profile_data = data.get("profile_data", {})
    profile_data[screen.field] = value
    await state.update_data(profile_data=profile_data)
    await _show(call, state, screen, value)


@customization_options_router.callback_query(F.data.in_(BACK_CALLBACKS))
async def handle_back(call: CallbackQuery, state: FSMContext):
    """Back to the wizard's main screen."""
    await show_customization_menu(call, state)
