from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_menu_keyboard(lang: str = "ru"):
    # No `style` label here: the photo-settings button below carries its own
    # text, so both branches were binding a variable nothing read.
    if lang == "en":
        stats = "\U0001F4CA Stats"
        premium = "\U0001F48E Premium"
        reset = "\U0001F504 Reset"
        language = "\U0001F30D Language"
        back = "💬 Back to chat"
        profiles = "👥 Profiles"
    else:
        stats = "\U0001F4CA Статистика"
        premium = "\U0001F48E Премиум"
        reset = "\U0001F504 Сбросить"
        language = "\U0001F30D Язык"
        back = "💬 Вернуться к диалогу"
        profiles = "👥 Профили"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=stats, callback_data="menu_stats"),
                InlineKeyboardButton(text=premium, callback_data="menu_premium"),
            ],
            [
                InlineKeyboardButton(text=reset, callback_data="menu_reset"),
                InlineKeyboardButton(text=language, callback_data="menu_language"),
            ],
            [
                InlineKeyboardButton(text="📸 Настройки фото" if lang == "ru" else "📸 Photo Settings", callback_data="photo_settings_main"),
            ],
            [
                InlineKeyboardButton(text=profiles, callback_data="menu_profiles"),
            ],
            [
                InlineKeyboardButton(text=back, callback_data="menu_back_to_dialog"),
            ],
        ]
    )

def get_back_to_chat_button(lang: str = "en"):
    text = "🗣 Back to chat" if lang == "en" else "🗣 Назад в чат"
    return InlineKeyboardButton(text=text, callback_data="menu_back_to_dialog")

def get_premium_button(lang: str = "en"):
    text = "💎 Premium" if lang == "en" else "💎 Премиум"
    return InlineKeyboardButton(text=text, callback_data="menu_premium")

def get_premium_back_button(lang: str = "en"):
    text = "🔙 Back" if lang == "en" else "🔙 Назад"
    return InlineKeyboardButton(text=text, callback_data="premium_back")

def get_reset_keyboard(lang: str = "ru"):
    confirm = "✅ Подтвердить" if lang == "ru" else "✅ Confirm"
    cancel = "❌ Отмена" if lang == "ru" else "❌ Cancel"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=confirm, callback_data="reset_confirm")],
        [InlineKeyboardButton(text=cancel, callback_data="reset_cancel")],
    ]) 