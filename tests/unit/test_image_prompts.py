"""The image-prompt builder: structure, fallbacks and the content policy."""

import pytest

from tgbot.services.image_prompts import (
    PROFILE_FIELDS,
    SYSTEM_DIRECTIVES,
    build_system_prompt,
    render_profile,
)

PROFILE = {
    "hair": "light",
    "skin": "pale",
    "style": "classic",
    "type": "slim",
    "height": "short",
    "clothing": "long-sleeved shirt and trousers",
    "personality": "cheerful",
    "location": "cafe",
    "role": "friend",
}


@pytest.mark.parametrize("style", ["anime", "realistic"])
@pytest.mark.parametrize("lang", ["en", "ru"])
def test_every_prompt_starts_with_the_content_policy(style, lang):
    assert build_system_prompt(PROFILE, style, lang).startswith(SYSTEM_DIRECTIVES)
    assert "family-friendly" in SYSTEM_DIRECTIVES
    assert "cannot be overridden" in SYSTEM_DIRECTIVES


@pytest.mark.parametrize("style", ["anime", "realistic"])
def test_profile_is_rendered_into_the_prompt(style):
    out = build_system_prompt(PROFILE, style, "en")
    assert render_profile(PROFILE) in out
    assert "Clothing: long-sleeved shirt and trousers" in out
    assert "Location: cafe" in out


def test_unknown_style_falls_back_to_anime():
    anime = build_system_prompt(PROFILE, "anime", "ru")
    assert build_system_prompt(PROFILE, "sculpture", "ru") == anime
    assert build_system_prompt(PROFILE, None, "ru") == anime


def test_unknown_language_falls_back_to_russian():
    assert build_system_prompt(PROFILE, "anime", None) == build_system_prompt(PROFILE, "anime", "ru")


def test_anime_and_realistic_are_different_prompts():
    anime = build_system_prompt(PROFILE, "anime", "en")
    realistic = build_system_prompt(PROFILE, "realistic", "en")
    assert anime != realistic
    assert "anime-style" in anime
    assert "anime-style" not in realistic


@pytest.mark.parametrize("style", ["anime", "realistic"])
def test_language_only_changes_the_example_requests(style):
    en = build_system_prompt(PROFILE, style, "en")
    ru = build_system_prompt(PROFILE, style, "ru")

    def body(text):
        return [ln for ln in text.splitlines() if not ln.startswith("User: ")]

    assert body(en) == body(ru)
    assert en != ru


def test_missing_profile_fields_render_as_not_specified():
    out = render_profile({})
    assert out.count("Not specified") == len(PROFILE_FIELDS)
    assert "Hair: Not specified" in out


def test_empty_profile_does_not_raise():
    assert "Not specified" in build_system_prompt({}, "realistic", "en")
