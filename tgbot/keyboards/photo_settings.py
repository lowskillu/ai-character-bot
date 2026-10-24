from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import Optional

from tgbot.keyboards.options import build_option_keyboard

def get_photo_settings_main_text(lang: str = "ru") -> str:
    if lang == "ru":
        return (
            "📸 Настройки картинок\n\n"
            "Здесь можно выбрать стиль изображений и дополнительные параметры 🙂\n\n"
            "Выбирай настройку ниже:"
        )
    else:
        return (
            "📸 Picture settings\n\n"
            "Choose the image style and extra parameters here 🙂\n\n"
            "Choose an option below:"
        )

def get_photo_settings_main_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    photo_setting_buttons = [
        [InlineKeyboardButton(text="🎨 Стиль" if lang == "ru" else "🎨 Style", callback_data="photo_style_menu")],
        [InlineKeyboardButton(text="🛠 Параметры" if lang == "ru" else "🛠 Parameters", callback_data="photo_params_menu")],
        [InlineKeyboardButton(text="🔙 Назад" if lang == "ru" else "🔙 Back", callback_data="photo_settings_back_to_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=photo_setting_buttons)

# --- Parameters -> picture finish ---
def get_photo_skin_message(lang: str = "ru") -> str:
    if lang == "ru":
        return (
            "💆 Выбери обработку портрета:\n"
            "✨ *Естественная* — натуральная текстура и детали.\n"
            "🌸 *Мягкая* — сглаженная, мягкая картинка."
        )
    else:
        return (
            "💆 Choose the portrait finish:\n"
            "✨ *Natural* — natural texture and detail.\n"
            "🌸 *Soft* — a smooth, soft-focus look."
        )

def get_photo_skin_keyboard(lang: str = "ru", selected_skin: Optional[str] = None) -> InlineKeyboardMarkup:
    skin_options = [
        ("✨ Естественная" if lang == "ru" else "✨ Natural", "natural"),
        ("🌸 Мягкая" if lang == "ru" else "🌸 Soft", "soft"),
    ]
    return build_option_keyboard(
        skin_options,
        choose_prefix="photo_skin_choose_",
        back_callback="photo_params_back",
        lang=lang,
        selected=selected_skin,
        columns=1,
    )

# --- Parameters: main screen ---
def get_photo_params_menu_text(lang: str = "ru") -> str:
    if lang == "ru":
        return "🛠 Выберите параметр, который хотите настроить:"
    else:
        return "🛠 Select the parameter you want to adjust:"

def get_photo_params_menu_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    photo_params_buttons = [
        [InlineKeyboardButton(text="✨ Обработка" if lang == "ru" else "✨ Finish", callback_data="photo_skin_menu_select")],
        [InlineKeyboardButton(text="🔙 Назад" if lang == "ru" else "🔙 Back", callback_data="photo_settings_back_to_main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=photo_params_buttons)

# --- Image style (anime / realistic) ---
def get_photo_style_message(lang: str = "ru", selected_style: Optional[str] = None) -> str:
    if lang == "ru":
        return (
            "🎨 Выбери стиль для генерации фото:\n"
            "*Аниме* — яркие цвета, характерная рисовка.\n"
            "*Реализм* — фотореалистичные изображения."
        )
    else:
        return (
            "🎨 Choose a style for photo generation:\n"
            "*Anime* — vibrant colors, characteristic drawing style.\n"
            "*Realistic* — photorealistic images."
        )

def get_photo_style_keyboard(lang: str = "ru", selected_style: Optional[str] = None) -> InlineKeyboardMarkup:
    style_options = [
        ("🌸 Аниме" if lang == "ru" else "🌸 Anime", "anime"),
        ("📸 Реализм" if lang == "ru" else "📸 Realistic", "realistic"),
    ]
    return build_option_keyboard(
        style_options,
        choose_prefix="photo_style_choose_",
        back_callback="photo_settings_back_to_main",
        lang=lang,
        selected=selected_style,
        columns=1,
    )
