from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import Optional

admin_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="📬Broadcast", callback_data="broadcast"),
        ],
        [InlineKeyboardButton(text="✖️Close", callback_data="close")],
    ]
)


# Removed as dead: support_menu (pointed at https://t.me/username — an unedited
# template placeholder), cancel_menu, get_language_menu, get_profile_confirm_
# keyboard and choose_lang_continue_menu_en. None was referenced anywhere, and
# none of their callbacks ("cancel", "profile_confirm", "profile_change") had a
# handler, so rendering any of them would have produced buttons that do nothing.

back_admin = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="🔙Back", callback_data="back_admin")]]
)


choose_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="✔️Yes", callback_data="yes"),
        ],
        [InlineKeyboardButton(text="🔙Back", callback_data="back_admin")],
    ]
)

def choose_lang_continue_menu(lang: str = "ru"):
    """Confirm / change buttons for the language screen.

    Was two functions differing only in two button labels.
    """
    confirm = "Подтвердить ✅" if lang == "ru" else "Confirm ✅"
    change = "Изменить 🔄" if lang == "ru" else "Change 🔄"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=confirm, callback_data="lang_confirm"),
                InlineKeyboardButton(text=change, callback_data="lang_change"),
            ]
        ]
    )


def get_language_choice_keyboard():
    """The first screen a new user sees. Was built inline in two handlers."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en"),
                InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru"),
            ]
        ]
    )


def get_ready_to_start_keyboard(lang: str = "ru"):
    """Single "Начать" button. Was built inline in three handlers."""
    from tgbot.misc.start_message_text import get_start_button_text

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=get_start_button_text(lang), callback_data="start_main")]
        ]
    )


def get_agreement_keyboard(lang: str = "ru"):
    from tgbot.misc.branding import AGREEMENT_URL_EN, AGREEMENT_URL_RU

    if lang == "ru":
        agreement_url = AGREEMENT_URL_RU
        agreement_text = "📝 Пользовательское соглашение"
        accept_text = "✅ Принимаю"
    else:
        agreement_url = AGREEMENT_URL_EN
        agreement_text = "📝 User Agreement"
        accept_text = "✅ Accept"
    keyboard = []
    if agreement_url:
        keyboard.append([InlineKeyboardButton(text=agreement_text, url=agreement_url)])
    keyboard.append([InlineKeyboardButton(text=accept_text, callback_data="agreement_accept")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_style_keyboard(lang: str = "ru", selected_style: Optional[str] = None):
    if lang == "en":
        anime_text = "🌟 Anime style"
        realistic_text = "🎭 Realistic style"
    else:
        anime_text = "🌟 Аниме стиль"
        realistic_text = "🎭 Реалистичный стиль"
    if selected_style == "anime":
        anime_text = "✅ " + anime_text
    elif selected_style == "realistic":
        realistic_text = "✅ " + realistic_text
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=anime_text, callback_data="style_anime"),
            ],
            [
                InlineKeyboardButton(text=realistic_text, callback_data="style_realistic"),
            ],
        ]
    )
