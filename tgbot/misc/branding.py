"""Deployment-specific links and contacts.

These used to be hard-coded in several handlers. They come from the
environment so one codebase can run under any bot name.
"""

import os

# Shown on the premium, stats and quota screens, e.g. "@my_support".
SUPPORT_CONTACT = os.getenv("SUPPORT_CONTACT", "").strip()

# Optional channel the user must join before creating a character. Empty
# disables the check entirely.
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "").strip()
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "").strip() or (
    f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}" if CHANNEL_USERNAME else ""
)

# User agreement pages. When empty, the agreement screen shows no link button.
AGREEMENT_URL_RU = os.getenv("AGREEMENT_URL_RU", "").strip()
AGREEMENT_URL_EN = os.getenv("AGREEMENT_URL_EN", "").strip()


def support_line(lang: str, ru: str, en: str) -> str:
    """``"<text> — @contact"``, or an empty string when no contact is configured."""
    if not SUPPORT_CONTACT:
        return ""
    return f"{ru if lang == 'ru' else en} — {SUPPORT_CONTACT}"
