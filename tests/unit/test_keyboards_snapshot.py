"""Keyboards must keep rendering exactly the same buttons and callback data.

Safety net for de-duplicating the option pickers, which were five 85-90%
similar copies of the same loop. A changed callback_data silently breaks a
button, and nothing else in the suite would catch it.

The snapshot is generated on first run; commit it, and any later drift fails.
"""

import json
import pathlib

import pytest

from tgbot.handlers import customization_body, customization_options, visual_vnesnost
from tgbot.handlers.customization import get_customization_keyboard, get_name_choice_keyboard
from tgbot.keyboards import inline, menu, photo_settings, profiles

SNAPSHOT = pathlib.Path(__file__).parent / "snapshots" / "keyboards.json"


def render(markup):
    """Flatten a markup into [[ (text, callback_data|url), ... ], ...]."""
    return [
        [(b.text, b.callback_data or b.url) for b in row]
        for row in markup.inline_keyboard
    ]


def collect():
    out = {}
    for lang in ("ru", "en"):
        out[f"customization_{lang}"] = render(get_customization_keyboard(lang))
        out[f"name_choice_{lang}"] = render(get_name_choice_keyboard(lang))
        out[f"name_choice_selected_{lang}"] = render(get_name_choice_keyboard(lang, "Саша"))

        for name, screen in customization_options.SCREENS.items():
            out[f"{name}_{lang}"] = render(screen.keyboard(lang))
        out[f"appearance_main_{lang}"] = render(
            visual_vnesnost.get_appearance_main_keyboard(lang)
        )
        # The option grid itself was never covered, which is how a dead
        # "💾 Save" button survived in the builder: every call site passed
        # saved=True, so it was never rendered and its handler was unreachable.
        out[f"appearance_opts_{lang}"] = render(
            visual_vnesnost.get_appearance_option_keyboard(
                visual_vnesnost.APPEARANCE_HAIR_OPTIONS[lang], lang=lang
            )
        )
        out[f"appearance_opts_sel_{lang}"] = render(
            visual_vnesnost.get_appearance_option_keyboard(
                visual_vnesnost.APPEARANCE_HAIR_OPTIONS[lang], "light", lang=lang
            )
        )
        out[f"body_main_{lang}"] = render(customization_body.get_body_main_keyboard(lang))

        # Same builders, with a selection made -- this is where the checkmark
        # logic lives and where an off-by-one in the loop would show up.
        out[f"clothing_sel_{lang}"] = render(
            customization_options.SCREENS["clothing"].keyboard(lang, "Long-sleeved shirt and trousers")
        )
        out[f"role_sel_{lang}"] = render(
            customization_options.SCREENS["role"].keyboard(lang, "friend")
        )

        out[f"menu_{lang}"] = render(menu.get_menu_keyboard(lang))
        out[f"reset_{lang}"] = render(menu.get_reset_keyboard(lang))
        out[f"agreement_{lang}"] = render(inline.get_agreement_keyboard(lang))
        out[f"style_{lang}"] = render(inline.get_style_keyboard(lang))
        out[f"photo_settings_{lang}"] = render(
            photo_settings.get_photo_settings_main_keyboard(lang)
        )
        out[f"photo_params_{lang}"] = render(photo_settings.get_photo_params_menu_keyboard(lang))
        out[f"photo_skin_{lang}"] = render(photo_settings.get_photo_skin_keyboard(lang, None))
        out[f"photo_style_{lang}"] = render(
            photo_settings.get_photo_style_keyboard(lang, "anime")
        )
        out[f"profiles_menu_{lang}"] = render(
            profiles.get_profiles_menu_keyboard([(1, "Саша"), (2, "Alex")], 0, False, lang)
        )
        out[f"new_user_{lang}"] = render(profiles.get_new_user_keyboard(lang))
        out[f"profiles_pick_{lang}"] = render(
            profiles.get_profiles_keyboard([(1, "Саша"), (2, "Alex")], False, lang)
        )
        out[f"edit_profile_{lang}"] = render(
            profiles.get_edit_profile_keyboard([(1, "Саша"), (2, "Alex")], lang)
        )
    return out


@pytest.fixture(scope="module")
def snapshot():
    current = collect()
    if not SNAPSHOT.exists():
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(
            json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        pytest.skip(f"wrote initial snapshot to {SNAPSHOT}; re-run to check against it")
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def test_no_keyboard_drift(snapshot):
    current = collect()
    assert sorted(current) == sorted(snapshot), "a keyboard was added or removed"
    for name in sorted(snapshot):
        # Compare as JSON so tuples and lists do not differ spuriously.
        assert json.loads(json.dumps(current[name])) == snapshot[name], (
            f"keyboard {name!r} changed"
        )


def test_every_callback_data_is_unique_within_a_keyboard(snapshot):
    for name, rows in snapshot.items():
        data = [cb for row in rows for _, cb in row if cb]
        assert len(data) == len(set(data)), f"{name} has duplicate callback_data"
