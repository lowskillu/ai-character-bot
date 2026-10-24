from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def get_character_photo_preview_keyboard(lang: str = "ru", profile_id: int = 0) -> InlineKeyboardMarkup:
    """Return inline keyboard with Regenerate and Confirm buttons in user's language."""
    is_ru = (lang or "ru").lower() == "ru"
    buttons = [
        [
            InlineKeyboardButton(
                text="🔄 Перегенерировать" if is_ru else "🔄 Regenerate",
                callback_data=f"char_photo_regen:{profile_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="👍 Мне всё нравится" if is_ru else "👍 Looks good!",
                callback_data=f"char_photo_confirm:{profile_id}",
            ),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
