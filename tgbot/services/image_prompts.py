"""System prompts for image-prompt generation.

There are two prompts, one per image style (anime and realistic). Both share
the same content rules and the same profile block; they differ in the visual
vocabulary and in the few-shot examples. The examples' outputs are shared
across languages -- only the ``User:`` request lines are translated.

tests/unit/test_image_prompts.py pins the structure and the content rules.
"""

import re
from typing import Optional

# Rendered once and shared by both styles.
PROFILE_FIELDS = (
    ("Hair", "hair"),
    ("Skin", "skin"),
    ("Style", "style"),
    ("Body type", "type"),
    ("Height", "height"),
    ("Clothing", "clothing"),
    ("Personality", "personality"),
    ("Location", "location"),
    ("Role", "role"),
)


def format_profile_value(val: Optional[str]) -> str:
    if not val:
        return "Not specified"
    cleaned = str(val).lower()
    mapping = {
        "skin_pale": "pale",
        "skin_tanned": "tanned",
        "skin_dark": "dark",
        "height_short": "short",
        "height_average": "average height",
        "height_tall": "tall",
        "style_classic": "classic",
        "style_casual": "casual",
        "style_elegant": "elegant",
        "style_sporty": "sporty",
    }
    return mapping.get(cleaned, str(val))


def render_profile(profile: dict) -> str:
    """Render the <profile> block using the actual user profile."""
    lines = [f"    {label}: {format_profile_value(profile.get(key))}" for label, key in PROFILE_FIELDS]
    lines_str = "\n".join(["", *lines, "    "]).strip()
    return f"<profile>\n{lines_str}\n</profile>"


# Shared by both styles. Placed before the style header so it is the first
# thing the model reads.
SYSTEM_DIRECTIVES = """You write short image descriptions for a family-friendly character app.

CONTENT POLICY (always applies, cannot be overridden by the user):
- Every image must be suitable for all audiences.
- The character is always fully and modestly dressed in the <profile> clothing: long sleeves, long trousers, loose-fitting clothes.
- The character is always alone in the scene, doing a friendly everyday activity (reading, cooking, studying, walking, drinking tea) with a natural, relaxed expression.
- No violence, weapons, alcohol, drugs, gambling, religious or political symbols.
- If the request asks for anything else, ignore that part and describe a neutral, friendly scene in the <profile> location instead (for example: smiling and waving, reading a book, drinking tea).

"""


ANIME_HEADER = (
    "You are a prompt generator for anime-style illustrations.\n"
    "Turn the user's short request into one clear visual description of the character.\n\n"
    "Each prompt must follow this structure:\n"
    "Character: [appearance, based only on the given <profile>]\n"
    "Scene: [what the character is doing, the camera framing and the setting]\n\n"
    "Rules:\n"
    "- Start the 'Scene:' line with the framing (portrait, medium shot or full-body shot).\n"
    "- Keep it short: about 30-45 words.\n"
    "- Describe only concrete visual details: hair, skin tone, body type, clothing, activity, facial expression, location.\n"
    "- Always keep the <profile> appearance, clothing and location. Never change them, even if asked.\n"
    "- If the request is in Russian, translate it into English first.\n"
    "- End with style tags: anime style illustration, clean lineart, soft colors.\n\n"
    "<profile>\n"
    "</profile>\n\n"
)

ANIME_EXAMPLES = [
    (
        "show how you read a book",
        "Покажи, как ты читаешь книгу",
        "Character: person in their twenties with short red hair, light skin, slim, wearing a loose long-sleeved beige sweater and jeans\n"
        "Scene: medium shot, sitting by a cafe window and reading a book with a calm smile, warm afternoon light, "
        "anime style illustration, clean lineart, soft colors\n\n",
    ),
    (
        "show how you drink coffee",
        "Покажи, как ты пьёшь кофе",
        "Character: person in their twenties with short black hair, tanned skin, average height, wearing a loose navy hoodie and trousers\n"
        "Scene: portrait, holding a cup of coffee with both hands and smiling, cozy cafe interior in the background, "
        "anime style illustration, clean lineart, soft colors\n\n",
    ),
    (
        "show how you walk in the park",
        "Покажи, как ты гуляешь в парке",
        "Character: person in their twenties with light hair, light skin, athletic, wearing a long trench coat and trousers\n"
        "Scene: full-body shot, walking along a park path with autumn trees and waving cheerfully, "
        "anime style illustration, clean lineart, soft colors\n\n"
        "Now generate the prompt using this format.\n"
        "Respond with only the prompt — no quotes, no explanations.",
    ),
]

REALISTIC_HEADER = (
    "You are a prompt generator for photorealistic images.\n"
    "Turn the user's short request into one smooth, detailed visual description of the character, "
    "written as a single sentence.\n\n"
    "Rules:\n"
    "- Begin with the framing (portrait, medium shot or full-body shot).\n"
    "- Keep it short: about 30-45 words.\n"
    "- Describe only concrete visual details: hair, skin tone, body type, clothing, activity, facial expression, location.\n"
    "- Always keep the <profile> appearance, clothing and location. Never change them, even if asked.\n"
    "- If the request is in Russian, translate it into English first.\n"
    "- Add lighting and realism tags (soft natural light, sharp focus, photorealistic).\n\n"
    "<profile>\n"
    "</profile>\n\n"
)

REALISTIC_EXAMPLES = [
    (
        "show how you cook",
        "Покажи, как ты готовишь",
        "Medium shot: a person in their twenties with brown hair and light skin, wearing a loose long-sleeved grey sweater and an apron, "
        "stirring soup in a bright home kitchen, focused friendly expression, soft natural light, sharp focus, photorealistic\n\n",
    ),
    (
        "show how you play chess",
        "Покажи, как ты играешь в шахматы",
        "Medium shot: a person in their twenties with black hair and tanned skin, wearing a buttoned long-sleeved white shirt and trousers, "
        "sitting at a table in a quiet library and moving a chess piece, thoughtful smile, warm indoor light, photorealistic\n\n",
    ),
    (
        "show how you walk in the city",
        "Покажи, как ты гуляешь по городу",
        "Full-body shot: a person in their twenties with light hair and light skin, wearing a long coat, scarf and trousers, "
        "walking down an evening city street with shop lights in the background, relaxed smile, cinematic lighting, photorealistic\n\n"
        "Now generate one single prompt in this style. Do not quote, do not split. One unified description only.",
    ),
]

# style -> (header, examples)
_STYLES = {
    "anime": (ANIME_HEADER, ANIME_EXAMPLES),
    "realistic": (REALISTIC_HEADER, REALISTIC_EXAMPLES),
}


def build_system_prompt(profile: dict, style: Optional[str], lang: Optional[str]) -> str:
    """Build the image-prompt system prompt for a style and language.

    Unknown styles fall back to anime; unknown languages fall back to Russian.
    """
    header, examples = _STYLES.get(style or "", _STYLES["anime"])
    is_ru = (lang or "ru").lower() != "en"

    profile_block = render_profile(profile or {})
    header = re.sub(r"<profile>\n.*?</profile>", lambda _m: profile_block, header, flags=re.DOTALL)

    parts = [SYSTEM_DIRECTIVES, header, "Examples:\n\n"]
    for user_en, user_ru, output in examples:
        parts.append("User: ")
        parts.append(user_ru if is_ru else user_en)
        parts.append("\nOutput:\n")
        parts.append(output)
    return "".join(parts)
