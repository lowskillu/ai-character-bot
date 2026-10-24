"""One builder for the option-picker keyboards.

Clothing, personality, location and role each had their own copy of the same
loop — measured 85-90% identical to one another — and customization.py carried
a fifth, dead copy of all four. They differ only in the option list and the
callback prefix.

tests/unit/test_keyboards_snapshot.py pins the rendered output, so this
consolidation is verifiable rather than hopeful.
"""

from typing import Iterable, Optional, Sequence, Tuple

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# Appended to the label of the currently selected option.
SELECTED_MARK = " ✅"
COLUMNS = 2


def back_button(lang: str, callback_data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text="🔙 Назад" if lang == "ru" else "🔙 Back",
        callback_data=callback_data,
    )


def build_option_keyboard(
    options: Sequence[Tuple[str, str]],
    choose_prefix: str,
    back_callback: str,
    lang: str = "ru",
    selected: Optional[str] = None,
    columns: int = COLUMNS,
) -> InlineKeyboardMarkup:
    """Render ``(label, value)`` pairs as a grid plus a back button.

    Args:
        options: ``(label, value)`` pairs, already in the target language.
        choose_prefix: callback prefix, e.g. ``"clothing_choose_"``.
        back_callback: callback data for the trailing back button.
        selected: value whose label gets a checkmark.
    """
    buttons: list[InlineKeyboardButton] = []
    for label, value in options:
        text = label + SELECTED_MARK if selected == value else label
        buttons.append(
            InlineKeyboardButton(text=text, callback_data=f"{choose_prefix}{value}")
        )

    rows = [buttons[i:i + columns] for i in range(0, len(buttons), columns)]
    rows.append([back_button(lang, back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def localized(options_ru: Iterable, options_en: Iterable, lang: str):
    """Pick the option list for a language, defaulting to Russian."""
    return options_ru if lang == "ru" else options_en
