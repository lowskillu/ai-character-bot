"""Helpers for the "replace the current message with a screen" pattern.

Twelve handlers across photo.py, menu.py and the customization modules were
90-99% identical copies of the same three lines, several of them differing only
in which callback triggered them.
"""

import logging
from typing import Optional

import aiogram
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

logger = logging.getLogger(__name__)


async def show_screen(
    call: CallbackQuery,
    text: str,
    keyboard: Optional[InlineKeyboardMarkup] = None,
    parse_mode: Optional[str] = None,
    answer_text: Optional[str] = None,
) -> None:
    """Edit the current message into a new screen, then answer the callback.

    Telegram rejects an edit that would not change anything. That is not an
    error for us — it just means the user pressed the button they were already
    on — so it is swallowed here rather than in every caller.
    """
    try:
        if hasattr(call.message, "edit_text"):
            await call.message.edit_text(text, reply_markup=keyboard, parse_mode=parse_mode)
        else:
            # InaccessibleMessage has no edit_text; send a new message instead.
            await call.message.answer(text, reply_markup=keyboard, parse_mode=parse_mode)
    except aiogram.exceptions.TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await call.answer(answer_text) if answer_text else await call.answer()
