import logging
import re
from contextlib import suppress
from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from tgbot.services import runware
from tgbot.services.runware import IImageInference, async_runware_request
from tgbot.services.profile import get_active_profile
from tgbot.services import premium, quotas
from tgbot.services.limits import (
    Busy,
    Overloaded,
    busy_message,
    limits,
    overloaded_message,
    user_lock,
)
from tgbot.misc.screens import show_screen
from tgbot.database.orm import AsyncORM
from tgbot.database.models import Profile, User
from typing import Optional, Dict, Any, cast
from tgbot.services.prompt_formation import generate_photo_prompt, get_negative_prompt
from tgbot.services.dialog_history import get_profile_history_from_db, save_profile_message, trim_profile_history
from tgbot.services.chat import serialize_profile_for_ai
from tgbot.handlers.user import generate_chat_response
from tgbot.keyboards.photo_settings import (
    get_photo_settings_main_text, get_photo_settings_main_keyboard,
    get_photo_params_menu_text, get_photo_params_menu_keyboard,
    get_photo_skin_message, get_photo_skin_keyboard,
    get_photo_style_message, get_photo_style_keyboard
)
import asyncio
import random

photo_router = Router()
logger = logging.getLogger(__name__)

# Триггерные фразы для генерации фото
PHOTO_TRIGGERS = [
    "show", "send photo", "photo", "give photo", "give me photo",
    "покажи", "скинь фото", "отправь фото", "фото", "покажи мне",
    "show me", "send me photo", "отправь мне фото", "скинь"
]

# Quota logic lives in tgbot/services/quotas.py — the stats screen needs it too.

# Matched on word boundaries, longest trigger first. Plain substring matching
# meant "фотография", "showing" or "покажите" all fired image generation.
# (?<!\w)/(?!\w) rather than \b so multi-word triggers behave too.
_TRIGGER_RE = re.compile(
    r"(?<!\w)(?:"
    + "|".join(re.escape(t) for t in sorted(PHOTO_TRIGGERS, key=len, reverse=True))
    + r")(?!\w)",
    re.IGNORECASE,
)


def is_photo_trigger(text: str) -> bool:
    """Проверяет, является ли текст триггером для генерации фото"""
    if not text:
        return False
    return _TRIGGER_RE.search(text) is not None


@photo_router.message(StateFilter(None), F.text.func(is_photo_trigger))
async def photo_handler(
    message: Message,
    state: FSMContext,
    user: Optional[Dict[str, Any]] = None,
    redis=None,
):
    """Photo generation, with the same backpressure the chat path already had.

    This path was completely unguarded: no per-user lock and no concurrency
    ceiling, so one user tapping "покажи" twenty times bought twenty OpenRouter
    prompt calls and twenty queued Runware generations. The chat path has had
    ``user_lock`` since the load test; there was never a reason for this one to
    differ, and it is the more expensive of the two.
    """
    user_id = message.from_user.id
    logger.info("[photo] request from user %s", user_id)
    lang = user.get("language", "ru") if user else "ru"

    if redis is None:
        logger.error("[photo] Redis was not injected")
        await message.answer("Внутренняя ошибка. Попробуйте позже.")
        return

    try:
        async with user_lock(redis, user_id):
            await _run_photo_turn(message, lang, user_id, redis)
    except Busy:
        await message.answer(busy_message(lang))
    except Overloaded:
        await message.answer(overloaded_message(lang))
    except Exception as e:  # noqa: BLE001
        # Silence is the worst outcome: the user cannot tell whether to wait or
        # retry, so they retry — adding load exactly when there is none spare.
        logger.exception("[photo] unhandled failure for user %s: %s", user_id, e)
        with suppress(Exception):
            await message.answer(overloaded_message(lang))


async def _run_photo_turn(message: Message, lang: str, user_id: int, redis) -> None:
    text = message.text or ""

    orm = cast(AsyncORM, AsyncORM.users)
    async with orm._get_session() as session:
        user_obj = await session.get(orm.model, user_id)
        # effective_level, not the raw column: reading premium_level directly
        # ignored premium_until, so a lapsed subscriber kept the 50/day photo
        # allowance instead of falling back to the free lifetime quota.
        premium_level = premium.effective_level(user_obj)
        style = getattr(user_obj, "style", "anime") if user_obj else "anime"
        # Сохраняем параметры фото сразу, чтобы не обращаться к user_obj вне сессии
        photo_skin = getattr(user_obj, 'photo_skin', None)

    # Reserves the slot atomically; released again on every failure path below.
    # Deliberately not wrapped in a try/except that degrades to "allow": if the
    # counter cannot be written, an unmetered image path is a bill, so this one
    # fails closed. The chat path makes the opposite trade for the opposite
    # reason — a blocked conversation is worse than an uncounted message.
    if not await quotas.try_consume(redis, user_id, premium_level):
        if premium_level >= 1:
            await message.answer(
                "Лимит фото на сегодня исчерпан. Попробуйте завтра или апгрейдьте премиум."
                if lang == "ru" else
                "Today's photo limit is used up. Try tomorrow, or upgrade your premium."
            )
        else:
            await message.answer(
                "Лимит фото исчерпан. Получи премиум для большего количества фото!"
                if lang == "ru" else
                "You're out of photos. Get premium for more!"
            )
        return

    # The slot is handed back unless a photo actually reaches the user. The old
    # code released it in two of the four failure paths: a prompt-generation
    # failure silently cost a free user one of their two lifetime photos.
    delivered = False
    try:
        delivered = await _generate_and_send(
            message, lang, user_id, redis, text, style, photo_skin
        )
    finally:
        if not delivered:
            await quotas.release(redis, user_id, premium_level)


async def _generate_and_send(
    message: Message,
    lang: str,
    user_id: int,
    redis,
    text: str,
    style: str,
    photo_skin: Optional[str],
) -> bool:
    """Build the prompt, generate the image, deliver it. True if the user got a photo."""
    # Локализация сообщений ожидания
    if lang == 'ru':
        status_texts = [
            "📷 Секунду, готовлю фото…",
            "🎨 Ещё немного… подбираю ракурс и свет",
            "🔮 Почти готово!",
        ]
    else:
        status_texts = [
            "📷 One moment, preparing the photo…",
            "🎨 Just a bit more… picking the angle and lighting",
            "🔮 Almost there!",
        ]

    status_msg = await message.answer(status_texts[0])

    # Формируем промпт через сервис
    async def get_profile(uid: int) -> Optional[dict]:
        # Uses the shared client injected by ConfigMiddleware. This used to
        # build a brand-new Redis client (and pool) on every call and never
        # close it.
        active_profile_id = await get_active_profile(redis, uid)
        if active_profile_id:
            orm = cast(AsyncORM, AsyncORM.users)
            async with orm._get_session() as session:
                profile = await session.get(Profile, active_profile_id)
                user = await session.get(User, uid)  # Получаем пользователя для языка
                if profile:
                    import json
                    appearance = json.loads(profile.appearance) if profile.appearance else {}
                    body = json.loads(profile.body_type) if profile.body_type else {}
                    return {
                        "profile_id": profile.id,
                        "hair": appearance.get("hair"),
                        "skin": appearance.get("skin"),
                        "style": appearance.get("style"),
                        "type": body.get("type"),
                        "height": body.get("height"),
                        "clothing": profile.clothing,
                        "personality": profile.personality,
                        "location": profile.location,
                        "role": profile.role,
                        "reference_photo_url": getattr(profile, "reference_photo_url", None),
                        "language": getattr(user, "language", "ru") if user else "ru",  # Добавляем язык пользователя
                    }
        return None

    prof_data = await get_profile(user_id)
    ref_photo_url = prof_data.get("reference_photo_url") if prof_data else None
    
    user_states = {user_id: {"style": style}} if user_id else {}
    # Prompt building is an LLM call of its own; it gets its own ceiling so a
    # burst of photo requests cannot starve the chat path of OpenRouter slots.
    try:
        async with limits.guard(limits.prompt, "prompt"):
            prompt = await generate_photo_prompt(
                text=text,
                user_id=user_id,
                get_user_profile=get_profile,
                user_states=user_states
            )
    except Overloaded:
        with suppress(Exception):
            await status_msg.delete()
        raise

    if not prompt:
        # The status message used to be left behind here, so a failed request
        # stranded the "please wait" text in the chat forever.
        with suppress(Exception):
            await status_msg.delete()
        await message.answer(
            "Ошибка формирования промпта. Попробуйте позже."
            if lang == "ru" else
            "Could not build the prompt. Please try again later."
        )
        return False

    # После генерации prompt добавить параметры фото
    photo_params = []
    skin_map = {'natural': 'natural texture, sharp detail', 'soft': 'soft focus, smooth tones'}
    if photo_skin in skin_map:
        photo_params.append(skin_map[photo_skin])
    if photo_params:
        prompt = f"{prompt.strip()} ({', '.join(photo_params)})"
    
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
        # async_runware_request drops images that fail the content check.
        safety=runware.content_check(),
        outputFormat="JPG",
        lora=loras if loras else None,
    )

    async def update_status_msg():
        # Cancelled as soon as the image is ready, so the sleeps below never
        # delay delivery.
        try:
            await asyncio.sleep(10)
            await status_msg.edit_text(status_texts[1])
            await asyncio.sleep(10)
            await status_msg.edit_text(status_texts[2])
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    async def stop_status_updates():
        """Cancel the ticker and drop the status message."""
        # Was `status_updated['done'] = True; await update_task`. Setting a flag
        # does not interrupt asyncio.sleep, so awaiting the task blocked until
        # the full 20s had elapsed — on every single photo, even when
        # generation finished in three seconds.
        update_task.cancel()
        with suppress(asyncio.CancelledError):
            await update_task
        with suppress(Exception):
            await status_msg.delete()

    generation_failed = (
        "Ошибка генерации фото. Попробуйте позже."
        if lang == "ru" else
        "Photo generation failed. Please try again later."
    )

    update_task = asyncio.create_task(update_status_msg())
    try:
        # Image generation is the most expensive downstream call and is rate
        # limited upstream, so it sheds rather than queues. /metrics reported
        # image_slots_free from this semaphore while nothing ever acquired it.
        async with limits.guard(limits.image, "image"):
            image_url = await async_runware_request(
                user_id, request_image, reference_photo_url=ref_photo_url
            )
    except Overloaded:
        await stop_status_updates()
        raise
    except Exception as e:
        logger.exception("[photo] generation failed for user %s: %s", user_id, e)
        await stop_status_updates()
        await message.answer(generation_failed)
        return False

    await stop_status_updates()
    if not image_url:
        await message.answer(generation_failed)
        return False

    # Динамическая генерация подписи от лица персонажа
    ai_caption = None
    if prof_data and prof_data.get("profile_id"):
        profile_id = prof_data["profile_id"]
        try:
            async with AsyncORM.users._get_session() as session:
                history = await get_profile_history_from_db(session, user_id, profile_id, limit=10)
                profile_obj = await session.get(Profile, profile_id)
                if profile_obj and profile_obj.name:
                    prof_name = profile_obj.name
                    prof_desc = serialize_profile_for_ai(profile_obj)
                    logging.info("[photo] generating AI caption for user %s...", user_id)
                    ai_caption = await generate_chat_response(
                        user_id=user_id,
                        text=(
                            f"[Sends photo for user request: '{text}'. Visual scene prompt: {prompt}.\n"
                            f"IMPORTANT: Write a SHORT, friendly in-character caption under this photo (max 1–2 brief PARAGRAPHS), "
                            f"matching the generated scene. Always reply in the exact language the user wrote in! Do NOT write long messages!]"
                        ),
                        lang=lang,
                        profile_name=prof_name,
                        profile_description_for_ai=prof_desc,
                        history=history
                    )
                    logging.info("[photo] AI caption result for user %s: %r", user_id, ai_caption)
        except Exception as e:
            logging.error("[photo] failed to generate AI caption for user %s: %s", user_id, e, exc_info=True)

    if ai_caption and ai_caption.strip():
        caption = ai_caption.strip()
        # Ограничиваем подпись не более чем 3 абзацами
        paragraphs = [p for p in caption.split("\n") if p.strip()]
        if len(paragraphs) > 3:
            caption = "\n\n".join(paragraphs[:3])
        if len(caption) > 1020:
            caption = caption[:1017] + "..."
    else:
        captions_ru = [
            "Вот, держи фото 📸",
            "Готово! Как тебе? 🙂",
            "Вот как это выглядит прямо сейчас ✨",
            "Готово~ Расскажи, понравилось ли 😊",
        ]
        captions_en = [
            "Here's the photo 📸",
            "Done! What do you think? 🙂",
            "This is how it looks right now ✨",
            "Done~ Let me know if you like it 😊",
        ]
        captions = captions_en if lang == 'en' else captions_ru
        caption = random.choice(captions)

    await message.answer_photo(image_url, caption=caption)

    if prof_data and prof_data.get("profile_id"):
        profile_id = prof_data["profile_id"]
        with suppress(Exception):
            async with AsyncORM.users._get_session() as session:
                await save_profile_message(session, user_id, profile_id, "user", text)
                await save_profile_message(session, user_id, profile_id, "bot", caption)
                await trim_profile_history(session, user_id, profile_id, keep=15)
                await session.commit()

    return True

# Two callbacks, one screen: "open settings" and "back to settings" rendered
# byte-identical bodies.
@photo_router.callback_query(F.data.in_({"photo_settings_main", "photo_settings_back_to_main"}))
async def handle_photo_settings_main(call: CallbackQuery, state: FSMContext, user: dict = None):
    lang = user.get("language", "ru") if user else "ru"
    await show_screen(call, get_photo_settings_main_text(lang), get_photo_settings_main_keyboard(lang))

@photo_router.callback_query(F.data == "photo_style_menu")
async def handle_photo_style_menu(call: CallbackQuery, state: FSMContext, user: dict = None):
    lang = user.get("language", "ru") if user else "ru"
    user_id = call.from_user.id
    async with AsyncORM.users._get_session() as session:
        user_obj = await session.get(User, user_id)
        selected_style = getattr(user_obj, "style", "anime")

    text = get_photo_style_message(lang, selected_style)
    keyboard = get_photo_style_keyboard(lang, selected_style)
    await call.message.edit_text(text, reply_markup=keyboard)
    await call.answer()

@photo_router.callback_query(F.data.startswith("photo_style_choose_"))
async def handle_photo_style_choose(call: CallbackQuery, state: FSMContext, user: dict = None):
    lang = user.get("language", "ru") if user else "ru"
    new_style = call.data[len("photo_style_choose_"):]
    user_id = call.from_user.id

    async with AsyncORM.users._get_session() as session:
        user_obj = await session.get(User, user_id)
        if user_obj:
            user_obj.style = new_style
            await session.flush() # Сохраняем изменение

    text = get_photo_style_message(lang, new_style)
    keyboard = get_photo_style_keyboard(lang, new_style)
    await call.message.edit_text(text, reply_markup=keyboard)
    await call.answer("Стиль сохранен!" if lang == "ru" else "Style saved!")

@photo_router.callback_query(F.data.in_({"photo_params_menu", "photo_params_back"}))
async def handle_photo_params_menu(call: CallbackQuery, state: FSMContext, user: dict = None):
    lang = user.get("language", "ru") if user else "ru"
    await show_screen(call, get_photo_params_menu_text(lang), get_photo_params_menu_keyboard(lang))

# --- Handlers for Skin options ---
@photo_router.callback_query(F.data == "photo_skin_menu_select")
async def handle_photo_skin_select(call: CallbackQuery, state: FSMContext, user: dict = None):
    lang = user.get("language", "ru") if user else "ru"
    user_id = call.from_user.id
    async with AsyncORM.users._get_session() as session:
        user_obj = await session.get(User, user_id)
        selected_skin = getattr(user_obj, "photo_skin", None)
    text = get_photo_skin_message(lang)
    keyboard = get_photo_skin_keyboard(lang, selected_skin)
    await call.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    await call.answer()

@photo_router.callback_query(F.data.startswith("photo_skin_choose_"))
async def handle_photo_skin_choose(call: CallbackQuery, state: FSMContext, user: dict = None):
    lang = user.get("language", "ru") if user else "ru"
    new_skin = call.data[len("photo_skin_choose_"):]
    user_id = call.from_user.id
    async with AsyncORM.users._get_session() as session:
        user_obj = await session.get(User, user_id)
        if user_obj:
            user_obj.photo_skin = new_skin
            await session.flush()
    text = get_photo_skin_message(lang)
    keyboard = get_photo_skin_keyboard(lang, new_skin)
    await call.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    await call.answer("Сохранено!" if lang == "ru" else "Saved!")

@photo_router.callback_query(F.data == "photo_settings_back_to_menu")
async def handle_photo_settings_back_to_menu(call: CallbackQuery, state: FSMContext, user: dict = None):
    from tgbot.handlers.menu import get_menu_text_and_keyboard # Импортируем для возврата в главное меню
    lang = user.get("language", "ru") if user else "ru"
    text, keyboard = get_menu_text_and_keyboard(lang)
    await call.message.edit_text(text, reply_markup=keyboard)
    await call.answer()
