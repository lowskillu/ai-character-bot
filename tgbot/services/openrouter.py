"""Everything that configures a call to a model, in one place.

Model ids used to be hard-coded literals — the chat model in handlers/user.py,
the prompt-builder model in services/prompt_formation.py, and the two image
models inline in handlers/photo.py. Model choice is the most direct
cost-versus-quality lever this bot has, and changing it meant editing three
files and rebuilding the image; there was no way to roll back a bad model or
try a cheaper one without a deploy.

The endpoint, key and attribution headers were also declared twice, verbatim,
in user.py and prompt_formation.py.

Reading the env at import is deliberate and matches how the rest of the tree
handles credentials: these are process-lifetime settings, not per-request ones.
"""

import os

API_KEY = os.getenv("OPENROUTER_API_KEY")
API_URL = os.getenv("OPENROUTER_API_URL", "https://openrouter.ai/api/v1/chat/completions")

# Sent as HTTP-Referer / X-Title for OpenRouter attribution. "https://bot.url"
# was an unedited placeholder.
SITE_URL = os.getenv("SITE_URL", "")
SITE_NAME = os.getenv("SITE_NAME", "AI Character Bot")

# --- models ---------------------------------------------------------------
# Character chat.
CHAT_MODEL = os.getenv("CHAT_MODEL", "meta-llama/llama-3.3-70b-instruct")

# Turns picture requests into image descriptions.
PROMPT_MODEL = os.getenv("PROMPT_MODEL", "meta-llama/llama-3.3-70b-instruct")

# --- sampling -------------------------------------------------------------
# Exposed alongside the models because a model swap almost always needs these
# retuned; leaving them hard-coded is what makes a swap a code change.
CHAT_TEMPERATURE = float(os.getenv("CHAT_TEMPERATURE", "0.9"))
CHAT_MAX_TOKENS = int(os.getenv("CHAT_MAX_TOKENS", "1000"))
PROMPT_TEMPERATURE = float(os.getenv("PROMPT_TEMPERATURE", "0.7"))
PROMPT_MAX_TOKENS = int(os.getenv("PROMPT_MAX_TOKENS", "4000"))

# How many past turns are replayed to the chat model. The database keeps
# HISTORY_LIMIT (10) per profile; this is how many of them are actually sent, so
# the two are deliberately separate knobs — raising this improves continuity and
# costs tokens, without changing what is stored.
MAX_HISTORY_LENGTH = int(os.getenv("MAX_HISTORY_LENGTH", "5"))


def headers() -> dict:
    """Auth plus the attribution headers OpenRouter expects."""
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": SITE_URL,
        "X-Title": SITE_NAME,
    }


# The image model is Runware's, not OpenRouter's — it lives in services/runware.py.
