"""Every button a keyboard renders must have a handler registered for it.

This is the check that makes the handler de-duplication safe. Several screens
were merged so that one handler now serves several callbacks via F.data.in_();
if one of those callbacks were dropped, the button would silently do nothing
and no other test would notice.

Static on purpose: it reads the registered filters out of the source rather
than dispatching real updates, so it needs neither a database nor Telegram.
"""

import json
import pathlib
import re

import pytest

HANDLERS_DIR = pathlib.Path(__file__).resolve().parents[2] / "tgbot" / "handlers"
SNAPSHOT = pathlib.Path(__file__).resolve().parents[1] / "unit" / "snapshots" / "keyboards.json"

# Buttons that intentionally have no handler in this bot.
EXEMPT_PREFIXES = ("http://", "https://")


def _registered():
    """Collect exact callback values and startswith prefixes from the sources.

    Mostly static, plus the registrations that are built at runtime:
    customization_body and visual_vnesnost register ``F.data.in_(set(...))`` so
    their field dicts stay the single source of truth and cannot drift from the
    decorator. Read those directly rather than teaching the regex to evaluate
    Python.
    """
    from tgbot.handlers.customization_body import BODY_FIELDS
    from tgbot.handlers.customization_options import (
        BACK_CALLBACKS,
        CHOOSE_PREFIXES,
        OPEN_CALLBACKS,
    )
    from tgbot.handlers.visual_vnesnost import APPEARANCE_FIELDS

    exact: set[str] = (
        set(BODY_FIELDS) | set(APPEARANCE_FIELDS) | OPEN_CALLBACKS | BACK_CALLBACKS
    )
    prefixes: list[str] = list(CHOOSE_PREFIXES)
    for path in HANDLERS_DIR.glob("*.py"):
        src = path.read_text(encoding="utf-8")
        exact.update(re.findall(r'F\.data\s*==\s*"([^"]+)"', src))
        for block in re.findall(r"F\.data\.in_\(\s*[\[{](.*?)[\]}]\s*\)", src, re.S):
            exact.update(re.findall(r'"([^"]+)"', block))
        prefixes.extend(re.findall(r'F\.data\.startswith\("([^"]+)"\)', src))
        # Regex-matched callbacks, e.g. r"^profile_select_(\d+)$"
        for rx in re.findall(r'F\.data\.regexp\(r"([^"]+)"\)', src):
            prefixes.append(rx.lstrip("^").split("(")[0])
    return exact, prefixes


def _all_callback_data():
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    out = set()
    for rows in data.values():
        for row in rows:
            for _text, cb in row:
                if cb and not cb.startswith(EXEMPT_PREFIXES):
                    out.add(cb)
    return sorted(out)


EXACT, PREFIXES = _registered()


@pytest.mark.parametrize("callback_data", _all_callback_data())
def test_button_has_a_handler(callback_data):
    if callback_data in EXACT:
        return
    if any(callback_data.startswith(p) for p in PREFIXES):
        return
    pytest.fail(
        f"no handler registered for callback_data {callback_data!r} — "
        "the button would silently do nothing"
    )


def test_merged_screens_kept_every_callback():
    """Callbacks that used to have their own handler and now share one."""
    for cb in (
        "photo_settings_main",
        "photo_settings_back_to_main",
        "photo_params_menu",
        "photo_params_back",
        "cancel_language_change",
        "back_to_menu",
        "premium_back",
        "style_back",
        "reset_cancel",
        "body_type",
        "body_height",
        "appearance_hair",
        "appearance_skin",
        "appearance_style",
        # Four separate modules collapsed into customization_options.
        "customize_clothing",
        "customize_personality",
        "customize_location",
        "customize_role",
        "clothing_back",
        "personality_back",
        "location_back",
        "role_back",
    ):
        assert cb in EXACT, f"{cb} lost its handler during consolidation"


def test_every_option_screen_still_answers_its_choose_prefix():
    from tgbot.handlers.customization_options import SCREENS

    for name, screen in SCREENS.items():
        for lang in ("ru", "en"):
            for _label, value in screen.options[lang]:
                cb = f"{name}_choose_{value}"
                assert any(cb.startswith(p) for p in PREFIXES), (
                    f"no handler would match {cb!r}"
                )
