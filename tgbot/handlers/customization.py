from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
import logging
from typing import Optional
import json
import random
from aiogram import Bot
from aiogram.types import InaccessibleMessage

from contextlib import suppress
from typing import cast
from tgbot.database.models import Profile, User
from tgbot.database.orm import AsyncORM
from tgbot.services import premium, quotas, runware
from tgbot.services.limits import limits
from tgbot.services.runware import IImageInference, async_runware_request
from tgbot.services.prompt_formation import generate_photo_prompt, get_negative_prompt
from tgbot.keyboards.character_photo import get_character_photo_preview_keyboard
from tgbot.services.profile import (
    create_profile, get_user_profiles, set_active_profile, update_profile
)
from tgbot.misc.branding import CHANNEL_LINK, CHANNEL_USERNAME
from tgbot.misc.states import ProfileCustomizationState
from tgbot.misc.welcome_message import get_welcome_message
from tgbot.misc.screens import show_screen
# Moved to misc/customization_view.py so the sibling handlers can import them
# without importing this module. Re-exported here for existing callers.
from tgbot.misc.customization_view import (  # noqa: F401
    format_profile_preview,
    get_customization_keyboard,
    show_customization_menu,
)
# Explicit, in one place. This used to be three separate imports from the same
# module, one of them a `import *` sitting between the other two — and the star
# silently shadowed an explicit `CHARACTER_NAMES_*` imported from
# services.profile just above it. The result was that a whole second copy of
# those lists was dead without anyone noticing.
from tgbot.misc.localization import (
    APPEARANCE_HAIR_OPTIONS,
    APPEARANCE_SKIN_OPTIONS,
    APPEARANCE_STYLE_OPTIONS,
    CHARACTER_NAMES_EN,
    CHARACTER_NAMES_RU,
    BODY_TYPE_OPTIONS,
    CLOTHING_OPTIONS_EN,
    CLOTHING_OPTIONS_RU,
    CUSTOMIZATION_TEXTS,
    HEIGHT_OPTIONS,
    LOCATION_OPTIONS_LOCALIZED,
    PERSONALITY_OPTIONS_EN,
    PERSONALITY_OPTIONS_RU,
    ROLE_OPTIONS_LOCALIZED,
)

customization_router = Router()
logger = logging.getLogger(__name__)

# Channel subscription keyboard

def get_subscription_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📲 Наш канал" if lang == "ru" else "📲 Our channel", url=CHANNEL_LINK)],
            [InlineKeyboardButton(
                text="✅ Готово, проверить" if lang == "ru" else "✅ Done, check",
                callback_data="check_subscription",
            )],
        ]
    )

SUBSCRIPTION_TEXT_RU = (
    "🔔 Подпишись на наш канал, чтобы быть в курсе новостей и обновлений бота 📰\n\n"
    "После подписки нажми «Готово, проверить» 🙂"
)
SUBSCRIPTION_TEXT_EN = (
    "🔔 Subscribe to our channel to keep up with bot news and updates 📰\n\n"
    "After subscribing, tap «Done, check» 🙂"
)

async def is_user_subscribed(bot: Bot, user_id: int) -> bool:
    # No channel configured: nothing to check.
    if not CHANNEL_USERNAME:
        return True
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False

def get_name_choice_keyboard(lang: str = "ru", selected_name: Optional[str] = None) -> InlineKeyboardMarkup:
    """Keyboard for picking a name."""
    names = CHARACTER_NAMES_RU if lang == "ru" else CHARACTER_NAMES_EN
    name_buttons = []
    
    # First 16 names: 8 rows of 2 buttons
    for name in names[:16]:
        display = name
        if selected_name and selected_name == name:
            display += " ✅"
        name_buttons.append(InlineKeyboardButton(text=display, callback_data=f"choose_name_{name}"))
    
    rows = [name_buttons[i:i+2] for i in range(0, len(name_buttons), 2)]
    rows.append([InlineKeyboardButton(text=CUSTOMIZATION_TEXTS[lang]["random_name"], callback_data="random_name")])
    rows.append([InlineKeyboardButton(text=CUSTOMIZATION_TEXTS[lang]["back"], callback_data="name_back")])
    
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _default_profile_data(lang: str) -> dict:
    """Starting values for a new character (values from the localized option lists)."""
    return {
        "name": "Саша" if lang == "ru" else "Alex",
        "appearance_hair": APPEARANCE_HAIR_OPTIONS[lang][0][1],
        "appearance_skin": APPEARANCE_SKIN_OPTIONS[lang][0][1],
        "appearance_style": APPEARANCE_STYLE_OPTIONS[lang][0][1],
        "body_type": BODY_TYPE_OPTIONS[lang][0][1],
        "body_height": HEIGHT_OPTIONS[lang][1][1],
        "clothing": (CLOTHING_OPTIONS_RU if lang == "ru" else CLOTHING_OPTIONS_EN)[0][1],
        "personality": (PERSONALITY_OPTIONS_RU if lang == "ru" else PERSONALITY_OPTIONS_EN)[0][1],
        "location": LOCATION_OPTIONS_LOCALIZED[lang][0][1],
        "role": ROLE_OPTIONS_LOCALIZED[lang][0][1],
    }


@customization_router.callback_query(F.data == "profile_create")
async def start_profile_customization(call: CallbackQuery, state: FSMContext, user: dict = None, bot = None):
    """Start the character wizard."""
    lang = user.get("language", "ru") if user else "ru"
    if bot is None:
        bot = call.bot  # fallback
    user_id = call.from_user.id
    from aiogram import Bot as AiogramBot
    real_bot = bot if isinstance(bot, AiogramBot) else call.bot
    assert isinstance(real_bot, Bot)
    if not await is_user_subscribed(real_bot, user_id):
        text = SUBSCRIPTION_TEXT_RU if lang == "ru" else SUBSCRIPTION_TEXT_EN
        if call.message and not isinstance(call.message, InaccessibleMessage):
            await call.message.edit_text(text, reply_markup=get_subscription_keyboard(lang))
        await call.answer()
        return
    default_profile_data = _default_profile_data(lang)
    await state.set_state(ProfileCustomizationState.customizing)
    await state.update_data(profile_data=default_profile_data, language=lang)
    preview_text = format_profile_preview(default_profile_data, lang)
    await call.message.edit_text(preview_text, reply_markup=get_customization_keyboard(lang), parse_mode="HTML")
    await call.answer()

# All three name screens (open, pick, randomise) rendered the same thing. The
# text was Russian-only regardless of language; the English side is added here.
def _name_screen_text(lang: str, name: str) -> str:
    chosen = name != "—"
    if lang == "ru":
        return (
            "👑 Давай выберем имя для персонажа\n\n"
            "Просто выбери понравившееся имя из списка ниже! 🙂\n"
            f"Текущее имя: <b>{name}</b>{' ✅' if chosen else ''}"
        )
    return (
        "👑 Let's pick a name for your character\n\n"
        "Just choose a name you like from the list below! 🙂\n"
        f"Current name: <b>{name}</b>{' ✅' if chosen else ''}"
    )


async def _show_name_screen(call: CallbackQuery, state: FSMContext, name: str) -> None:
    lang = (await state.get_data()).get("language", "ru")
    await show_screen(
        call,
        _name_screen_text(lang, name),
        get_name_choice_keyboard(lang, selected_name=name if name != "—" else None),
        parse_mode="HTML",
    )


async def _set_name(state: FSMContext, name: str) -> None:
    data = await state.get_data()
    profile_data = data.get("profile_data", {})
    profile_data["name"] = name
    await state.update_data(profile_data=profile_data)


@customization_router.callback_query(F.data == "customize_name")
async def handle_customize_name(call: CallbackQuery, state: FSMContext):
    """Open the name screen."""
    data = await state.get_data()
    await state.update_data(current_field="name")
    await _show_name_screen(call, state, data.get("profile_data", {}).get("name", "—"))


@customization_router.callback_query(F.data.startswith("choose_name_"))
async def handle_choose_name(call: CallbackQuery, state: FSMContext):
    """Pick a name from the list."""
    name = call.data[len("choose_name_"):]
    await _set_name(state, name)
    await _show_name_screen(call, state, name)


@customization_router.callback_query(F.data == "random_name")
async def handle_random_name(call: CallbackQuery, state: FSMContext):
    """Pick a random name."""
    lang = (await state.get_data()).get("language", "ru")
    name = random.choice(CHARACTER_NAMES_RU if lang == "ru" else CHARACTER_NAMES_EN)
    await _set_name(state, name)
    await _show_name_screen(call, state, name)


@customization_router.callback_query(F.data == "name_back")
async def handle_name_back(call: CallbackQuery, state: FSMContext):
    """Back to the wizard's main screen."""
    lang = (await state.get_data()).get("language", "ru")
    profile_data = (await state.get_data()).get("profile_data", {})
    preview_text = format_profile_preview(profile_data, lang)
    await call.message.edit_text(preview_text, reply_markup=get_customization_keyboard(lang))
    await call.answer()

# "customize_appearance" is owned by tgbot/handlers/visual_vnesnost.py, which
# owns the rest of the appearance sub-menu. A byte-equivalent copy used to be
# registered here too; because customization_router comes first, it won and the
# StateFilter-guarded version in visual_vnesnost.py was dead code.

# --- Random character ---
@customization_router.callback_query(F.data == "customize_random")
async def handle_customize_random(call: CallbackQuery, state: FSMContext):
    lang = (await state.get_data()).get("language", "ru")
    # The local import that used to sit here shadowed the module-level one with
    # a different, shorter list — so "random look" and "random name" drew from
    # two different pools.
    name = random.choice(CHARACTER_NAMES_RU if lang == "ru" else CHARACTER_NAMES_EN)
    hair = random.choice(APPEARANCE_HAIR_OPTIONS[lang])[1]
    skin = random.choice(APPEARANCE_SKIN_OPTIONS[lang])[1]
    style = random.choice(APPEARANCE_STYLE_OPTIONS[lang])[1]
    body_type = random.choice(BODY_TYPE_OPTIONS[lang])[1]
    height = random.choice(HEIGHT_OPTIONS[lang])[1]
    clothing = random.choice([v for _, v in (CLOTHING_OPTIONS_RU if lang == "ru" else CLOTHING_OPTIONS_EN)])
    personality = random.choice([v for _, v in (PERSONALITY_OPTIONS_RU if lang == "ru" else PERSONALITY_OPTIONS_EN)])
    location = random.choice(LOCATION_OPTIONS_LOCALIZED[lang])[1]
    role = random.choice(ROLE_OPTIONS_LOCALIZED[lang])[1]
    profile_data = {
        "name": name,
        "appearance_hair": hair,
        "appearance_skin": skin,
        "appearance_style": style,
        "body_type": body_type,
        "body_height": height,
        "clothing": clothing,
        "personality": personality,
        "location": location,
        "role": role,
    }
    await state.update_data(profile_data=profile_data, language=lang)
    preview_text = format_profile_preview(profile_data, lang)
    await call.message.edit_text(preview_text, reply_markup=get_customization_keyboard(lang))
    await call.answer()

@customization_router.callback_query(F.data == "customize_finish")
async def handle_customize_finish(call: CallbackQuery, state: FSMContext, redis=None):
    lang = (await state.get_data()).get("language", "ru")
    profile_data = (await state.get_data()).get("profile_data", {})
    editing_profile_id = (await state.get_data()).get("editing_profile_id")
    if not profile_data.get("name") or profile_data.get("name") == "—":
        await call.answer("Пожалуйста, укажите хотя бы имя персонажа!" if lang == "ru" else "Please set at least the character name!", show_alert=True)
        return
    # Shared client from ConfigMiddleware. This used to construct a new Redis
    # client and connection pool per call, and never closed it.
    if redis is None:
        logger.error("[customize_finish] Redis was not injected")
        await call.answer("Внутренняя ошибка. Попробуйте позже.", show_alert=True)
        return
    # Profile limit (only when creating a new one)
    async with AsyncORM.users._get_session() as session:
        user_obj = await session.get(AsyncORM.users.model, call.from_user.id)
        # effective_level applies premium_until; the raw column did not, so an
        # expired subscriber kept the four-profile allowance indefinitely.
        premium_level = premium.effective_level(user_obj)
        profiles = await get_user_profiles(session, call.from_user.id)
        max_profiles = 4 if premium_level >= 1 else 2
        if not editing_profile_id and len(profiles) >= max_profiles:
            await call.answer(
                "У вас уже максимальное количество профилей!" if lang == "ru" else "You already have the maximum number of profiles!",
                show_alert=True
            )
            return
    # appearance and body are stored as JSON
    appearance = json.dumps({
        "hair": profile_data.get("appearance_hair"),
        "skin": profile_data.get("appearance_skin"),
        "style": profile_data.get("appearance_style"),
    }, ensure_ascii=False)
    body = json.dumps({
        "type": profile_data.get("body_type"),
        "height": profile_data.get("body_height"),
    }, ensure_ascii=False)
    fields = dict(
        name=profile_data.get("name"),
        appearance=appearance,
        body_type=body,
        clothing=profile_data.get("clothing"),
        personality=profile_data.get("personality"),
        location=profile_data.get("location"),
        role=profile_data.get("role"),
    )
    try:
        async with AsyncORM.users._get_session() as session:
            if editing_profile_id:
                # Update in place. This used to delete the row and insert a new
                # one, and both profile_message_history foreign keys cascade —
                # so a user who edited an outfit lost the whole conversation.
                profile = await update_profile(
                    session, call.from_user.id, editing_profile_id, **fields
                )
                if profile is None:
                    logger.warning(
                        "[customize_finish] profile %s not found for user %s; creating instead",
                        editing_profile_id, call.from_user.id,
                    )
            else:
                profile = None

            user_obj = await session.get(User, call.from_user.id)
            user_style = (getattr(user_obj, "style", None) or "anime").lower()

            if profile is None:
                profile = await create_profile(
                    session=session,
                    user_id=call.from_user.id,
                    style=user_style,
                    description=None,
                    **fields,
                )
            else:
                profile = await update_profile(
                    session, call.from_user.id, editing_profile_id, style=user_style
                )
            # Read the id while the session is still open
            new_profile_id = profile.id if profile else None
        # Clear editing_profile_id once done
        await state.update_data(editing_profile_id=None)
        await state.clear()
        if new_profile_id:
            await set_active_profile(redis, call.from_user.id, new_profile_id)

            welcome_message = get_welcome_message(lang)
            with suppress(Exception):
                await call.message.edit_text(welcome_message)
            return
    except Exception as e:
        # No `import logging` here. A local import binds the name for the whole
        # function scope, which made the module-level logger at the top of this
        # function raise UnboundLocalError instead of reporting the problem.
        logger.exception("Error saving profile for user %s: %s", call.from_user.id, e)
        await call.answer("Ошибка при сохранении профиля!" if lang == "ru" else "Error saving profile!", show_alert=True)
        return


async def _generate_char_preview_photo(user_id: int, profile_id: int, redis, lang: str = "ru") -> Optional[str]:
    """Generate initial or regenerated portrait photo for character preview."""
    orm = cast(AsyncORM, AsyncORM.users)
    async with orm._get_session() as session:
        profile = await session.get(Profile, profile_id)
        if not profile:
            return None

        user_obj = await session.get(User, user_id)
        style = (profile.style or getattr(user_obj, "style", None) or "anime").lower()
        appearance = json.loads(profile.appearance) if profile.appearance else {}
        body = json.loads(profile.body_type) if profile.body_type else {}

        async def get_profile_async(uid: int) -> dict:
            return {
                "hair": appearance.get("hair"),
                "skin": appearance.get("skin"),
                "style": appearance.get("style"),
                "type": body.get("type"),
                "height": body.get("height"),
                "clothing": profile.clothing,
                "personality": profile.personality,
                "location": profile.location,
                "role": profile.role,
                "language": lang,
            }

        prompt = await generate_photo_prompt(
            text="First portrait photo of the character, friendly smile, in the profile location",
            user_id=user_id,
            get_user_profile=get_profile_async,
            user_states={user_id: {"style": style}},
        )
        if not prompt:
            prompt = f"portrait of a friendly person in their twenties, smiling, {profile.appearance or ''}, wearing {profile.clothing or ''}, high quality"

        loras = runware.loras_for_style(style)
        request_image = IImageInference(
            positivePrompt=prompt,
            model=runware.model_for_style(style),
            numberResults=1,
            negativePrompt=get_negative_prompt(style),
            height=runware.IMAGE_HEIGHT,
            width=runware.IMAGE_WIDTH,
            steps=runware.IMAGE_STEPS,
            CFGScale=runware.IMAGE_CFG_SCALE,
            safety=runware.content_check(),
            outputFormat="JPG",
            lora=loras if loras else None,
        )

        try:
            async with limits.guard(limits.image, "image"):
                image_url = await async_runware_request(user_id, request_image)
        except Exception as e:
            logger.exception("Error generating preview photo for profile %s: %s", profile_id, e)
            return None

        if image_url:
            await redis.set(f"temp_char_photo:{user_id}:{profile_id}", image_url, ex=3600)
        return image_url


@customization_router.callback_query(F.data.startswith("char_photo_regen:"))
async def char_photo_regen_handler(call: CallbackQuery, user: dict = None, redis = None, bot = None):
    lang = user.get("language", "ru") if user else "ru"
    user_id = call.from_user.id
    premium_level = user.get("premium_level", 0) if user else 0
    try:
        profile_id = int(call.data.split(":")[1])
    except (IndexError, ValueError):
        await call.answer("Invalid profile", show_alert=True)
        return

    # A regeneration costs one picture from the quota
    consumed = await quotas.try_consume(redis, user_id, premium_level)
    if not consumed:
        limit_text = (
            "Ваш дневной лимит фото исчерпан! Оформите Премиум, чтобы генерировать больше фото."
            if lang == "ru" else
            "Daily photo limit reached! Get Premium to generate more photos."
        )
        await call.answer(limit_text, show_alert=True)
        return

    await call.answer("Генерирую новое фото..." if lang == "ru" else "Generating new photo...")

    image_url = await _generate_char_preview_photo(user_id, profile_id, redis, lang)
    if not image_url:
        await quotas.release(redis, user_id, premium_level)
        await call.message.answer(
            "Не удалось сгенерировать новое фото. Попробуйте ещё раз."
            if lang == "ru" else
            "Failed to generate new photo. Please try again."
        )
        return

    kb = get_character_photo_preview_keyboard(lang, profile_id)
    caption = (
        "✨ Новое фото вашего персонажа сгенерировано!\n\n"
        "👍 Нажмите «Мне всё нравится», чтобы зафиксировать внешность и открыть чат.\n"
        "🔄 Нажмите «Перегенерировать» (⚠️ повторное нажатие спишет ещё 1 фото из вашего лимита)."
        if lang == "ru" else
        "✨ New character photo generated!\n\n"
        "👍 Tap 'Looks good!' to lock the appearance and open chat.\n"
        "🔄 Tap 'Regenerate' (⚠️ tapping again costs 1 more photo from your limit)."
    )
    with suppress(Exception):
        await call.message.delete()
    await call.message.answer_photo(photo=image_url, caption=caption, reply_markup=kb)


@customization_router.callback_query(F.data.startswith("char_photo_confirm:"))
async def char_photo_confirm_handler(call: CallbackQuery, user: dict = None, redis = None):
    lang = user.get("language", "ru") if user else "ru"
    user_id = call.from_user.id
    try:
        profile_id = int(call.data.split(":")[1])
    except (IndexError, ValueError):
        await call.answer("Invalid profile", show_alert=True)
        return

    temp_photo = await redis.get(f"temp_char_photo:{user_id}:{profile_id}")
    if temp_photo:
        if isinstance(temp_photo, bytes):
            temp_photo = temp_photo.decode("utf-8")
        orm = cast(AsyncORM, AsyncORM.users)
        async with orm._get_session() as session:
            await update_profile(session, user_id, profile_id, reference_photo_url=temp_photo)

    with suppress(Exception):
        await call.message.edit_reply_markup(reply_markup=None)

    await call.answer(
        "Внешность персонажа зафиксирована!"
        if lang == "ru" else
        "Character appearance locked!"
    )
    welcome_message = get_welcome_message(lang)
    await call.message.answer(welcome_message)

@customization_router.callback_query(F.data == "check_subscription")
async def check_subscription_handler(call: CallbackQuery, state: FSMContext, user: dict = None, bot = None):
    lang = user.get("language", "ru") if user else "ru"
    if bot is None:
        bot = call.bot
    user_id = call.from_user.id
    from aiogram import Bot as AiogramBot
    real_bot = bot if isinstance(bot, AiogramBot) else call.bot
    assert isinstance(real_bot, Bot)
    if await is_user_subscribed(real_bot, user_id):
        # Start the character wizard
        default_profile_data = _default_profile_data(lang)
        await state.set_state(ProfileCustomizationState.customizing)
        await state.update_data(profile_data=default_profile_data, language=lang)
        preview_text = format_profile_preview(default_profile_data, lang)
        if call.message and not isinstance(call.message, InaccessibleMessage):
            await call.message.edit_text(preview_text, reply_markup=get_customization_keyboard(lang), parse_mode="HTML")
        await call.answer()
    else:
        text = SUBSCRIPTION_TEXT_RU if lang == "ru" else SUBSCRIPTION_TEXT_EN
        await call.answer("Подписка не найдена, попробуй ещё раз." if lang == "ru" else "Subscription not found, please try again.", show_alert=True)
        if call.message and not isinstance(call.message, InaccessibleMessage):
            await call.message.edit_text(text, reply_markup=get_subscription_keyboard(lang))

@customization_router.message(ProfileCustomizationState.customizing)
async def handle_customization_input(message: Message, state: FSMContext):
    """Text typed while the wizard is open."""
    data = await state.get_data()
    if data.get("waiting_for_name_input"):
        return
    
    current_field = data.get("current_field")
    profile_data = data.get("profile_data", {})
    lang = data.get("language", "ru")
    
    if not current_field:
        await message.answer(
            "Пожалуйста, используйте кнопки меню для настройки" if lang == "ru" else 
            "Please use the menu buttons for customization"
        )
        return

    field_mapping = {
        "name": "name",
        "appearance": "appearance",
        "body": "body_type",
        "clothing": "clothing",
        "personality": "personality",
        "location": "location",
        "role": "role"
    }
    
    if current_field in field_mapping:
        profile_data[field_mapping[current_field]] = message.text
        await state.update_data(profile_data=profile_data, language=lang)
        
        await message.answer(
            "✅ Значение сохранено!" if lang == "ru" else "✅ Value saved!",
            reply_markup=get_customization_keyboard(lang)
        )
