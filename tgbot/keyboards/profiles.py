from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import List, Tuple

def get_new_user_keyboard(lang: str = "ru"):
    """Keyboard for a new user: only the create button."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=("➕ Создать новый" if lang == "ru" else "➕ New profile"), callback_data="profile_create")],
        ]
    )

def get_profiles_keyboard(profiles: List[Tuple[int, str]], is_premium: bool, lang: str = "ru"):
    """
    Profile picker.
    profiles: list of (id, name)
    is_premium: True allows up to 4 profiles, False up to 2

    The two action labels were Russian-only, so this — the first screen an
    English user sees after pressing "Start 🚀" — was half-translated.
    """
    keyboard = []
    for idx, (profile_id, name) in enumerate(profiles, 1):
        keyboard.append([
            InlineKeyboardButton(
                text=f"{idx}) {name}",
                callback_data=f"profile_select_{profile_id}"
            )
        ])
    max_profiles = 4 if is_premium else 2
    if len(profiles) < max_profiles:
        keyboard.append([
            InlineKeyboardButton(
                text="➕ Создать новый" if lang == "ru" else "➕ New profile",
                callback_data="profile_create",
            )
        ])
    if profiles:
        keyboard.append([
            InlineKeyboardButton(
                text="❌ Удалить существующий" if lang == "ru" else "❌ Delete profile",
                callback_data="profile_delete",
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_profiles_menu_keyboard(profiles: list, active_profile_id: int, is_premium: bool, lang: str = "ru"):
    """
    Profile menu: marks the active profile, with create / delete / edit / back.
    profiles: list of (id, name)
    active_profile_id: id of the active profile
    is_premium: True allows up to 4 profiles, False up to 2
    lang: interface language
    """
    keyboard = []
    for idx, (profile_id, name) in enumerate(profiles, 1):
        is_active = profile_id == active_profile_id
        text = f"{idx}) {name} {'✅' if is_active else ''}"
        keyboard.append([
            InlineKeyboardButton(
                text=text,
                callback_data=f"profile_select_{profile_id}"
            )
        ])
    max_profiles = 4 if is_premium else 2
    if len(profiles) < max_profiles:
        keyboard.append([
            InlineKeyboardButton(text="➕ Создать новый" if lang == "ru" else "➕ New profile", callback_data="profile_create")
        ])
    if profiles:
        keyboard.append([
            InlineKeyboardButton(text="\u274c Удалить существующий" if lang == "ru" else "\u274c Delete profile", callback_data="profile_delete")
        ])
        keyboard.append([
            InlineKeyboardButton(text="🎀 Изменить профиль" if lang == "ru" else "🎀 Edit profile", callback_data="edit_profile")
        ])
    # Add Back button to menu
    keyboard.append([
        InlineKeyboardButton(text="⬅️ Назад" if lang == "ru" else "⬅️ Back", callback_data="menu_back_to_dialog")
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_edit_profile_keyboard(profiles: list, lang: str = "ru"):
    keyboard = []
    for idx, (profile_id, name) in enumerate(profiles, 1):
        keyboard.append([
            InlineKeyboardButton(
                text=f"{idx}) {name}",
                callback_data=f"edit_profile_select_{profile_id}"
            )
        ])
    keyboard.append([
        InlineKeyboardButton(text="⬅️ Назад" if lang == "ru" else "⬅️ Back", callback_data="menu_back_to_dialog")
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
