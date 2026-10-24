import logging
import re
from typing import Optional

from tgbot.services import openrouter
from tgbot.services.http import get_http_session
from tgbot.services.image_prompts import build_system_prompt

# Endpoint, key, attribution headers and the model id come from
# tgbot/services/openrouter.py; this module used to declare its own copy of the
# first three and hard-code the fourth.
# Timeouts live on the shared session in tgbot/services/http.py.


from tgbot.database.orm import AsyncORM
from tgbot.services.dialog_history import get_profile_history_from_db


async def generate_photo_prompt(
    text: str,
    user_id: int,
    get_user_profile,
    user_states,
    history: Optional[list] = None,
) -> Optional[str]:
    """
    Generates a photo prompt using OpenRouter API via aiohttp.
    
    Args:
        text (str): User's request text
        user_id (int): User's Telegram ID
        get_user_profile: Function to get user's profile
        user_states: User states dictionary
        history (list, optional): Dialogue history turns
        
    Returns:
        Optional[str]: Generated prompt or None if error occurs
    """
    try:
        request_text = text

        profile = await get_user_profile(user_id)
        if not profile:
            logging.warning(f"No profile found for user {user_id} when generating photo prompt.")
            return None

        # Fetch recent dialogue history (last 15 turns) if not explicitly provided
        profile_id = profile.get("profile_id") or profile.get("id")
        if history is None and profile_id:
            try:
                async with AsyncORM.users._get_session() as session:
                    history = await get_profile_history_from_db(session, user_id, profile_id, limit=15)
            except Exception as hist_err:
                logging.warning(f"Could not load history for photo prompt user {user_id}: {hist_err}")
                history = None

        recent_dialogue_str = ""
        if history:
            dialogue_lines = []
            for item in history:
                role = "User" if item.get("role") == "user" else "Character"
                msg_text = item.get("text", "").strip()
                if msg_text:
                    dialogue_lines.append(f"{role}: {msg_text}")
            if dialogue_lines:
                recent_dialogue_str = "<recent_dialogue>\n" + "\n".join(dialogue_lines) + "\n</recent_dialogue>\n\n"

        # Style from user_states if given, otherwise from the profile
        if user_states and user_id in user_states and user_states[user_id].get('style'):
            style = user_states[user_id]['style'].lower()
        else:
            style = (profile.get('style') or '').lower()
        lang = (profile.get('language') or 'ru').lower()
        system_prompt = build_system_prompt(profile, style, lang)

        user_content = f"{recent_dialogue_str}User's photo request: {request_text}"

        payload = {
            "model": openrouter.PROMPT_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "temperature": openrouter.PROMPT_TEMPERATURE,
            "max_tokens": openrouter.PROMPT_MAX_TOKENS,
        }

        # Only metadata at INFO. The payload contains the user's message and a
        # long system prompt; logging it wrote gigabytes of user content to disk
        # per day.
        session = await get_http_session()
        logging.info("[generate_photo_prompt] calling OpenRouter for user %s with request: %r", user_id, request_text)
        logging.debug("[generate_photo_prompt] payload for user %s: %s", user_id, payload)

        async with session.post(
            openrouter.API_URL, headers=openrouter.headers(), json=payload
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
        logging.debug("[generate_photo_prompt] raw response for user %s: %s", user_id, data)

        prompt = data.get("choices", [{}])[0].get("message", {}).get("content")
        if not prompt:
            prompt = data.get("choices", [{}])[0].get("text")
        if not isinstance(prompt, str) or not prompt.strip():
            logging.error("Generated prompt for user %s is not usable: %r", user_id, type(prompt))
            return None

        # A declined request is never sent again. The safe fallback below
        # describes the character from the profile alone; the user's text is
        # left out on purpose, so whatever the model declined never reaches
        # the image model either.
        if is_refusal(prompt):
            logging.warning("[generate_photo_prompt] model declined for user %s; using the safe fallback", user_id)
            return safe_fallback_prompt(profile)

        logging.info("[generate_photo_prompt] OpenRouter returned prompt for user %s:\n%s", user_id, prompt)
        return prompt

    except Exception as e:
        logging.error(f"Error in generate_photo_prompt for user {user_id}: {e}", exc_info=True)
        return None


REFUSAL_MARKERS = (
    "i'm sorry", "i cannot", "cannot fulfill", "as an ai",
    "unable to", "content policy", "against my guidelines", "извините", "не могу",
    "无法", "抱歉", "不能", "违规", "相关内容",
)


def is_refusal(prompt: str) -> bool:
    """True when the model answered with a refusal instead of a description."""
    lowered = prompt.lower()
    return any(m in lowered for m in REFUSAL_MARKERS) or bool(re.search(r"[\u4e00-\u9fff]", prompt))


def safe_fallback_prompt(profile: dict) -> str:
    """A neutral everyday scene built from the profile only."""
    hair = profile.get("hair") or "light"
    skin = profile.get("skin") or "light skin"
    clothing = profile.get("clothing") or "long-sleeved sweater and jeans"
    location = profile.get("location") or "cafe"
    return (
        f"Character: {hair} hair, {skin}, wearing {clothing}, in {location}\n"
        "Scene: medium shot, the character smiles and waves, friendly everyday scene"
    )


def get_negative_prompt(style: Optional[str] = None) -> str:
    """
    Returns a default negative prompt for image generation.
    """
    return "(worst quality, low quality, normal quality, lowres, bad anatomy, bad hands, bad face, bad proportions, malformed limbs, blurry, blur, grain, noisy, jpeg artifacts, watermark, signature, text, logo, error, fused fingers, mutated hands, deformed face, blurry face, extra limbs, extra fingers, extra arms, extra legs, duplicate face, long neck, distorted eyes, cropped, out of frame, weapon, blood, alcohol, cigarette)"
