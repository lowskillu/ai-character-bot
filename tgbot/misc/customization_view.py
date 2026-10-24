"""Shared view code for the profile-customization wizard.

Lives below the handlers so they stop importing each other. Six handler
modules used to do

    from tgbot.handlers.customization import format_profile_preview, get_customization_keyboard

from *inside a function body*, purely to dodge the circular import that a
module-level version would have caused. Now everything imports downward.

show_customization_menu() also replaces six copies of the same back-button
handler, which the duplicate scan measured at 95-99%% identical.
"""

import logging

from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from tgbot.misc.localization import (
    APPEARANCE_HAIR_VALUE_TO_TEXT, APPEARANCE_SKIN_VALUE_TO_TEXT, APPEARANCE_STYLE_VALUE_TO_TEXT,
    BODY_TYPE_VALUE_TO_TEXT,
    HEIGHT_VALUE_TO_TEXT, CUSTOMIZATION_BUTTONS, CUSTOMIZATION_TEXTS,
    CLOTHING_OPTIONS_RU, CLOTHING_OPTIONS_EN, PERSONALITY_OPTIONS_RU, PERSONALITY_OPTIONS_EN,
    LOCATION_VALUE_TO_TEXT, ROLE_VALUE_TO_TEXT,
)

logger = logging.getLogger(__name__)


def get_customization_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    buttons = CUSTOMIZATION_BUTTONS[lang]
    main_buttons = [
        InlineKeyboardButton(text=buttons["name"], callback_data="customize_name"),
        InlineKeyboardButton(text=buttons["appearance"], callback_data="customize_appearance"),
        InlineKeyboardButton(text=buttons["body"], callback_data="customize_body"),
        InlineKeyboardButton(text=buttons["clothing"], callback_data="customize_clothing"),
        InlineKeyboardButton(text=buttons["personality"], callback_data="customize_personality"),
        InlineKeyboardButton(text=buttons["location"], callback_data="customize_location"),
        InlineKeyboardButton(text=buttons["role"], callback_data="customize_role"),
    ]
    rows = [main_buttons[i:i+2] for i in range(0, len(main_buttons), 2)]
    rows.append([InlineKeyboardButton(text=CUSTOMIZATION_TEXTS[lang]["random_profile"], callback_data="customize_random")])
    rows.append([InlineKeyboardButton(text=CUSTOMIZATION_TEXTS[lang]["finish_setup"], callback_data="customize_finish")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# --- Исправленный format_profile_preview ---
def format_profile_preview(profile_data: dict, lang: str = "ru") -> str:
    hair = APPEARANCE_HAIR_VALUE_TO_TEXT[lang].get(profile_data.get('appearance_hair') or '', '-')
    skin = APPEARANCE_SKIN_VALUE_TO_TEXT[lang].get(profile_data.get('appearance_skin') or '', '-')
    style = APPEARANCE_STYLE_VALUE_TO_TEXT[lang].get(profile_data.get('appearance_style') or '', '-')
    body_type_display = BODY_TYPE_VALUE_TO_TEXT[lang].get(profile_data.get('body_type') or '', '-')
    height_display = HEIGHT_VALUE_TO_TEXT[lang].get(profile_data.get('body_height') or '', '-')
    if lang == 'ru':
        clothing_map = {v: t for t, v in CLOTHING_OPTIONS_RU}
        personality_map = {v: t for t, v in PERSONALITY_OPTIONS_RU}
    else:
        clothing_map = {v: t for t, v in CLOTHING_OPTIONS_EN}
        personality_map = {v: t for t, v in PERSONALITY_OPTIONS_EN}
    clothing_key = str(profile_data.get('clothing') or '')
    personality_key = str(profile_data.get('personality') or '')
    clothing_display = clothing_map.get(clothing_key, clothing_key or '-')
    personality_display = personality_map.get(personality_key, personality_key or '-')
    location_key = str(profile_data.get('location') or '')
    role_key = str(profile_data.get('role') or '')
    location_display = LOCATION_VALUE_TO_TEXT[lang].get(location_key, location_key or '-')
    role_display = ROLE_VALUE_TO_TEXT[lang].get(role_key, role_key or '-')
    name = profile_data.get('name', '—')
    texts = CUSTOMIZATION_TEXTS[lang]
    return (
        f"{texts['profile_preview']}\n\n"
        f"👑 {texts['name_label']}: {name}\n"
        f"💇 {texts['appearance_label']}: {hair}, {skin}, {style}  \n"
        f"📐 {texts['body_label']}: {body_type_display}, {height_display}  \n"
        f"👕 {texts['clothing_label']}: {clothing_display}  \n"
        f"🐱 {texts['personality_label']}: {personality_display}  \n"
        f"🌇 {texts['location_label']}: {location_display}  \n"
        f"🎭 {texts['role_label']}: {role_display}  \n\n"
        f"{texts['can_change_params']}\n\n"
        f"{texts['save_warning']}\n\n"
        f"{texts['finish_setup']}"
    )

async def show_customization_menu(call: CallbackQuery, state) -> None:
    """Return to the wizard's main screen showing the current profile preview.

    This is the body that was copy-pasted into every *_back handler.
    """
    data = await state.get_data()
    lang = data.get("language", "ru")
    profile_data = data.get("profile_data", {})
    await call.message.edit_text(
        format_profile_preview(profile_data, lang),
        reply_markup=get_customization_keyboard(lang),
    )
    await call.answer()
