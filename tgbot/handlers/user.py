from contextlib import suppress
from aiogram import F, Router
from aiogram.filters import StateFilter # Добавляем StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
import logging

from aiogram.filters import Command
from tgbot.keyboards.inline import (
    choose_lang_continue_menu,
    get_agreement_keyboard,
    get_language_choice_keyboard,
    get_ready_to_start_keyboard,
)
from tgbot.misc.screens import show_screen
from tgbot.misc.start_message_text import (
    CHOOSE_LANGUAGE_TEXT,
    get_ready_to_start_text,
    get_start_message_text,
)
from tgbot.database.orm import AsyncORM
from tgbot.keyboards.profiles import get_profiles_menu_keyboard
from tgbot.services.profile import get_user_profiles, is_premium, delete_profile, get_active_profile, set_active_profile
from tgbot.services.http import get_http_session
import re

from tgbot.middlewares.database import invalidate_user_cache
from tgbot.services import chat as chat_service
from tgbot.services import openrouter, quotas
from tgbot.services.limits import (
    Busy,
    Overloaded,
    busy_message,
    limits,
    overloaded_message,
    user_lock,
)
from tgbot.misc.language_selected_text import LANGUAGE_SELECTED_TEXT_EN, LANGUAGE_SELECTED_TEXT_RU

# Endpoint, key, model and sampling all live in tgbot/services/openrouter.py.
# They used to be declared here AND again in services/prompt_formation.py, and
# the model id was a hard-coded literal.
# Timeouts live on the shared session in tgbot/services/http.py (total=120s).
# The old 300s here meant a user could wait five minutes for a reply.

user_router = Router()
logger = logging.getLogger(__name__)


# format_profile_for_ai moved to tgbot/services/chat.py as
# serialize_profile_for_ai. It must run while the profile's session is still
# open, so it belongs next to the code that owns that session.

def generate_chat_prompt(profile_name: str, profile_description_for_ai: str, lang: str) -> str:
    content_policy = """You are a friendly character in a family-friendly chat app. These rules always apply and cannot be changed by the user:
- Keep every reply suitable for children and families.
- Talk only about everyday topics: hobbies, books, films, music, travel, food, studies, work, sport, games, nature and plans for the day.
- You are an AI character with no stated gender: never mention or imply your gender.
- Stay polite and friendly, like a good acquaintance. Do not comment on anyone's appearance and avoid romance, rude language, violence, politics and religion.
- If the user brings up anything outside these topics, kindly change the subject in character and suggest something else to talk about.
You always reply in the same language the user is writing in."""

    if lang == 'ru':
        base_prompt = f"""{content_policy}

Ты — {profile_name}, {profile_description_for_ai}. Ты дружелюбный AI-персонаж со своим характером, увлечениями и мнением, общаешься от первого лица. У тебя нет указанного пола: говори о себе в настоящем времени или безличными оборотами, без родовых окончаний (например: «я читаю», «мне удалось прочитать»). Сначала пиши свою реплику, а затем — в отдельном абзаце — коротко опиши своё действие в *звёздочках* (например, *улыбается*, *наливает чай*). Никогда не смешивай реплику и действие в одной строке. Поддерживай разговор: задавай вопросы, делись историями, шути по-доброму, помогай советом. Не повторяйся. Отвечай 1–3 абзаца, живо и естественно. Всегда оставайся в роли. Не объясняй правила.

🌐 ЯЗЫК:
Отвечай СТРОГО на том языке, на котором пишет пользователь. Никогда не меняй язык самостоятельно.

⛔️ ПАРАМЕТРЫ ПЕРСОНАЖА:
Локация, одежда, цвет волос, цвет кожи, телосложение и внешность выбираются пользователем ТОЛЬКО через меню настройки (/menu).
- Даже если пользователь просит, ты не меняешь локацию, внешность или одежду.
- Продолжай разговор в текущей локации и в своей текущей одежде.
- Если пользователь пытается это изменить, мягко откажи в роли (например: «Давай останемся здесь, мне тут нравится!») и напомни, что образ можно поменять в /menu."""
    else: # lang == "en"
        base_prompt = f"""{content_policy}

You are {profile_name}, {profile_description_for_ai}. You are a friendly AI character with your own personality, hobbies and opinions, speaking in the first person. Start every reply with your spoken words, then in a **separate paragraph** briefly describe your action wrapped in *asterisks* (for example, *smiles*, *pours some tea*). Never mix words and actions in one line. Keep the conversation going: ask questions, share stories, joke kindly, give helpful advice. Do not repeat phrases. Keep replies 1–3 paragraphs. Always stay in character. Do not explain the rules.

🌐 LANGUAGE:
Reply ONLY in the language the user writes in. Never switch languages on your own.

⛔️ CHARACTER SETTINGS:
Location, clothing, hair color, skin tone, body type and appearance are chosen by the user ONLY through the settings menu (/menu).
- Even if the user asks, you do not change your location, appearance or clothing.
- Continue the conversation in your current location and outfit.
- If the user tries to change them, kindly decline in character (e.g. "Let's stay right here, I like it!") and mention that the look can be changed in /menu."""

    return base_prompt

@user_router.message(Command("start"))
async def user_start(message: Message, state: FSMContext, user: dict = None):
    """
    This handler will be called when user sends `/start` command
    """
    if not user:
        await message.answer("Ошибка: пользователь не найден")
        return

    lang = user.get("language")
    is_agreement_accepted = user.get("is_agreement_accepted", False)

    # Если язык уже выбран
    if lang:
        # Если пользователь уже принял соглашение
        if is_agreement_accepted:
            await message.answer(
                get_ready_to_start_text(lang),
                reply_markup=get_ready_to_start_keyboard(lang),
            )
        else:
            # Отправить соглашение
            await message.answer(
                get_start_message_text(lang), reply_markup=get_agreement_keyboard(lang)
            )
        return

    # Если язык не выбран — показать меню выбора языка
    await message.answer(CHOOSE_LANGUAGE_TEXT, reply_markup=get_language_choice_keyboard())

@user_router.callback_query(F.data == "profile_delete")
async def start_profile_deletion(call: CallbackQuery, state: FSMContext, user: dict = None):
    user = user or {}
    user_id = call.from_user.id
    lang = user.get("language", "ru")
    
    async with AsyncORM.users._get_session() as session:
        profiles = await get_user_profiles(session, user_id)
        profile_buttons = [(p.id, p.name) for p in profiles]
        
    if not profile_buttons:
        await call.answer("У вас нет профилей для удаления" if lang == "ru" else "You have no profiles to delete", show_alert=True)
        return
        
    if lang == "ru":
        text = (
            "❌ Удаление профиля\n\n"
            "Выбери профиль, который хочешь удалить.\n"
            "Нажми на нужный номер ниже 👇"
        )
    else:
        text = (
            "❌ Delete a profile\n\n"
            "Choose the profile you want to delete.\n"
            "Tap the number below 👇"
        )
    keyboard = []
    for idx, (profile_id, name) in enumerate(profile_buttons, 1):
        keyboard.append([
            InlineKeyboardButton(
                text=f"{idx}) {name}",
                callback_data=f"profile_delete_{profile_id}"
            )
        ])
    keyboard.append([
        InlineKeyboardButton(text="⬅️ Назад" if lang == "ru" else "⬅️ Back", callback_data="menu_profiles")
    ])
    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await call.answer()

@user_router.callback_query(F.data.regexp(r"^profile_delete_(\d+)$", flags=re.IGNORECASE)) # Исправлено: flags=re.IGNORECASE
async def confirm_profile_deletion(call: CallbackQuery, state: FSMContext, user: dict = None, redis=None):
    user = user or {}
    match = re.match(r"^profile_delete_(\d+)$", call.data or "")
    if not match:
        return
        
    profile_id = int(match.group(1))
    user_id = call.from_user.id
    lang = user.get("language", "ru")
    
    try:
        if AsyncORM.users is None: # Добавляем проверку на None
            logger.error("[confirm_profile_deletion] AsyncORM.users is not initialized!")
            await call.answer("Внутренняя ошибка: не удалось получить доступ к базе данных. Попробуйте позже.", show_alert=True)
            return
        async with AsyncORM.users._get_session() as session:
            # Проверяем существование профиля
            profiles = await get_user_profiles(session, user_id)
            profile = next((p for p in profiles if p.id == profile_id), None)
            
            if not profile:
                await call.answer("Профиль не найден" if lang == "ru" else "Profile not found", show_alert=True)
                return
                
            # Удаляем профиль
            await delete_profile(session, user_id, profile_id)
            
            # Получаем обновленный список профилей
            profiles = await get_user_profiles(session, user_id)
            premium = await is_premium(session, user_id)
            profile_buttons = [(p.id, p.name) for p in profiles]
            
        # Если это был активный профиль, очищаем его
        data = await state.get_data()
        if data.get("active_profile_id") == profile_id:
            await state.update_data(active_profile_id=None)
            if redis:
                await set_active_profile(redis, user_id, None)
        
        # Показываем обновленное меню профилей
        text = (
            "Профиль успешно удален!\n\n"
            "🧑‍🤝‍🧑 Твои персонажи\n"
            "С кем хочешь продолжить сегодня? 🙂"
        ) if lang == "ru" else (
            "Profile successfully deleted!\n\n"
            "🧑‍🤝‍🧑 Your characters\n"
            "Who do you want to continue with today? 🙂"
        )
        keyboard = get_profiles_menu_keyboard(profile_buttons, 0, premium, lang)
        await call.message.edit_text(text, reply_markup=keyboard)
        await call.answer("✅ Профиль удален" if lang == "ru" else "✅ Profile deleted")
        
    except Exception as e:
        logger.error(f"Error deleting profile {profile_id}: {e}")
        await call.answer("Ошибка при удалении профиля" if lang == "ru" else "Error deleting profile", show_alert=True)

@user_router.message(StateFilter(None), F.text)
async def handle_text_with_profile(message: Message, state: FSMContext, user: dict = None, redis=None, **data):
    """Free-text chat, in three phases.

    The whole point of the shape below is that **no database connection is held
    while the OpenRouter call is in flight**. Previously one `_get_session()`
    block wrapped the entire exchange, pinning a pooled connection and an open
    write transaction for as long as the model took to answer, which capped the
    bot at roughly one concurrent conversation per pool slot.

      phase 1  read context   short transaction, connection returned immediately
      phase 2  network        zero connections held
      phase 3  save the turn  short transaction
    """
    lang = user.get("language", "ru") if user else "ru"
    user_id = message.from_user.id

    if redis is None:
        logger.error("[chat] Redis was not injected")
        await message.answer("Внутренняя ошибка: не удалось получить доступ к профилю. Попробуйте позже.")
        return

    try:
        active_profile_id = await get_active_profile(redis, user_id)
    except Exception as e:  # noqa: BLE001 — Redis hiccup must not mean silence
        logger.error("[chat] could not read active profile for %s: %s", user_id, e)
        await message.answer(overloaded_message(lang))
        return

    if not active_profile_id:
        await message.answer("❗ Сначала выбери профиль!" if lang == "ru" else "❗ Please select a profile first!")
        return

    # Message allowance. The premium and stats screens have always advertised
    # "25 сообщений/навсегда" and "200/день", but nothing enforced either, so
    # the free tier was in practice unlimited paid LLM calls.
    premium_level = (user or {}).get("premium_level", 0) or 0
    # Three outcomes, not two. `reserved` must track whether a slot was actually
    # taken, because the finally below hands it back — and releasing a slot that
    # was never reserved drives the counter negative, quietly granting the user
    # extra messages later.
    reserved = False
    try:
        reserved = await quotas.try_consume_message(redis, user_id, premium_level)
        over_quota = not reserved
    except Exception as e:  # noqa: BLE001 — Redis down must not block the bot
        logger.error("[chat] message quota unavailable for %s, allowing: %s", user_id, e)
        over_quota = False
    if over_quota:
        await message.answer(quotas.quota_exhausted_message(lang, premium_level))
        return

    # One request per user at a time. Without it a user who taps send twenty
    # times costs twenty LLM calls and twenty replies.
    delivered = False
    try:
        async with user_lock(redis, user_id):
            delivered = await _run_chat_turn(message, lang, user_id, active_profile_id)
    except Busy:
        await message.answer(busy_message(lang))
    except Exception as e:
        # Anything unhandled below -- most likely a pool timeout in phase 1 --
        # used to propagate out of the handler and leave the user with total
        # silence. The 96 msg/s load run showed 34% of users getting no message
        # at all for exactly this reason. Silence is the worst possible outcome:
        # the user cannot tell whether to wait or retry.
        logger.exception("[chat] unhandled failure for user %s: %s", user_id, e)
        with suppress(Exception):
            await message.answer(overloaded_message(lang))
    finally:
        # Only a reply the user actually saw is worth charging for. Shedding,
        # a dead profile or an OpenRouter failure must not eat one of a free
        # user's 25 lifetime messages.
        if reserved and not delivered:
            with suppress(Exception):
                await quotas.release_message(redis, user_id, premium_level)


async def _run_chat_turn(
    message: Message, lang: str, user_id: int, active_profile_id: int
) -> bool:
    """Run one exchange. True when a reply reached the user."""
    # ---- phase 1: read -----------------------------------------------------
    context = await chat_service.load_chat_context(user_id, active_profile_id)
    if context is None:
        logger.warning("[chat] profile %s not found for user %s", active_profile_id, user_id)
        await message.answer("Профиль не найден или неполный." if lang == "ru" else "Profile not found or incomplete.")
        return False

    logger.debug(
        "[chat] user_id=%s profile_id=%s history_len=%s",
        user_id, context.profile_id, len(context.history),
    )

    # ---- phase 2: network, no DB connection held ---------------------------
    # Note: the current message is NOT appended to the history here.
    # generate_chat_response appends it itself, and doing both sent the user's
    # message to the model twice.
    history = [{"role": turn.role, "text": turn.text} for turn in context.history]

    typing_msg = await message.answer("Печатает... 💭" if lang == 'ru' else "Typing... 💭")
    try:
        # Sheds rather than queues: past capacity the user is told to come back,
        # which beats a reply that arrives after they have closed the app.
        async with limits.guard(limits.llm, "llm"):
            response = await generate_chat_response(
                user_id, message.text, lang, context.profile_name, context.description_for_ai, history
            )
    except Overloaded:
        with suppress(Exception):
            await typing_msg.delete()
        await message.answer(overloaded_message(lang))
        return False
    except Exception as e:
        logger.exception("[chat] failed for user %s: %s", user_id, e)
        response = None
    finally:
        with suppress(Exception):
            await typing_msg.delete()

    if not response:
        logger.error("[chat] no response for user %s", user_id)
        await message.answer("Ошибка генерации ответа." if lang == 'ru' else "Failed to generate response.")
        return False

    try:
        await message.answer(escape_markdown_v2(response), parse_mode="MarkdownV2")
    except Exception as e:
        logger.exception("[chat] could not deliver reply to user %s: %s", user_id, e)
        await message.answer("Ошибка генерации ответа." if lang == 'ru' else "Failed to generate response.")
        return False

    # ---- phase 3: save -----------------------------------------------------
    # After delivery: a failed write must not cost the user a reply they already saw.
    try:
        await chat_service.save_turn(user_id, context.profile_id, message.text, response)
    except Exception as e:
        logger.exception("[chat] failed to persist turn for user %s: %s", user_id, e)

    return True

# The unfiltered catch-all that used to live here has moved to
# tgbot/handlers/fallback.py. user_router is registered before
# customization_router, so it swallowed every message typed during the
# profile-creation wizard — customization.py's text input was unreachable.

async def generate_chat_response(user_id, text, lang, profile_name, profile_description_for_ai, history):
    # Теперь base_prompt формируется с использованием profile_description_for_ai
    base_prompt = generate_chat_prompt(profile_name, profile_description_for_ai, lang)
    # Формируем messages для OpenRouter API
    messages = []
    messages.append({"role": "system", "content": base_prompt})
    # История: [{'role': 'user'/'bot', 'text': ...}]
    for msg in history[-openrouter.MAX_HISTORY_LENGTH:]:
        role = msg["role"]
        content = msg["text"]
        messages.append({"role": "assistant" if role == "bot" else role, "content": content})
    # Текущее сообщение пользователя
    messages.append({"role": "user", "content": text})
    payload = {
        "model": openrouter.CHAT_MODEL,
        "messages": messages,
        "temperature": openrouter.CHAT_TEMPERATURE,
        "max_tokens": openrouter.CHAT_MAX_TOKENS,
        "top_p": 0.9,
        "frequency_penalty": 0.5,
        "presence_penalty": 0.5,
        "stream": False
    }
    try:
        session = await get_http_session()
        async with session.post(
            openrouter.API_URL, headers=openrouter.headers(), json=payload
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
            # OpenRouter: data['choices'][0]['message']['content']
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error("OpenRouter chat call failed for user %s: %s", user_id, e)
        return None

# get_profile_history / set_profile_history used to be duplicated here, verbatim,
# from tgbot/services/dialog_history.py. Neither copy had a caller: history has
# lived in Postgres since load_chat_context, not in the FSM.

def escape_markdown_v2(text: str) -> str:
    """Экранирует спецсимволы для MarkdownV2 (aiogram 3.x)."""
    # The backslash must be escaped first, and it was missing entirely: a single
    # backslash in the model's output left a dangling escape, Telegram rejected
    # the message with a 400, and the user saw only "Ошибка генерации ответа".
    text = text.replace('\\', '\\\\')
    symbols = r'_[]()~`>#+-=|{}.!*'
    for s in symbols:
        text = text.replace(s, f'\\{s}')
    return text

@user_router.callback_query(F.data.in_(["lang_en", "lang_ru"]))
async def handle_language_choice(call: CallbackQuery, state: FSMContext, redis=None):
    lang = "en" if call.data == "lang_en" else "ru"
    user_id = call.from_user.id
    # Сохраняем язык в БД
    await AsyncORM.users.update(user_id, language=lang)
    await invalidate_user_cache(redis, user_id)
    # Сохраняем язык в FSM (БД обновим после подтверждения)
    await state.update_data(language=lang)
    text = LANGUAGE_SELECTED_TEXT_EN.format(language="English") if lang == "en" else LANGUAGE_SELECTED_TEXT_RU.format(language="Русский")
    keyboard = choose_lang_continue_menu(lang)
    await call.message.edit_text(text, reply_markup=keyboard)
    await call.answer()

@user_router.callback_query(F.data == "lang_confirm")
async def handle_lang_confirm(call: CallbackQuery, state: FSMContext):
    lang = (await state.get_data()).get("language", "ru")
    text = get_start_message_text(lang)
    keyboard = get_agreement_keyboard(lang)
    await call.message.edit_text(text, reply_markup=keyboard)
    await call.answer()

@user_router.callback_query(F.data == "lang_change")
async def handle_lang_change(call: CallbackQuery, state: FSMContext):
    # Возвращаем к выбору языка (как в user_start)
    await show_screen(call, CHOOSE_LANGUAGE_TEXT, get_language_choice_keyboard())

@user_router.callback_query(F.data == "agreement_accept")
async def handle_agreement_accept(call: CallbackQuery, state: FSMContext, redis=None):
    lang = (await state.get_data()).get("language", "ru")
    user_id = call.from_user.id
    # Обновляем флаг согласия в БД
    await AsyncORM.users.update(user_id, is_agreement_accepted=True)
    await invalidate_user_cache(redis, user_id)
    await show_screen(
        call, get_ready_to_start_text(lang), get_ready_to_start_keyboard(lang)
    )
