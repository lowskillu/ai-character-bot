"""Photo trigger matching.

Regression guard for the substring matcher, which fired image generation on
any message merely containing "фото" or "show" as a substring.
"""

import pytest

from tgbot.handlers.photo import is_photo_trigger


@pytest.mark.parametrize(
    "text",
    [
        "покажи фото",
        "фото",
        "скинь",
        "Покажи мне",
        "send me photo",
        "show",
        "SHOW ME",
        "ну покажи, пожалуйста",
        "а можно фото?",
    ],
)
def test_matches_real_requests(text):
    assert is_photo_trigger(text) is True


@pytest.mark.parametrize(
    "text",
    [
        # Each of these used to fire because the trigger is a substring.
        "фотография у тебя красивая",
        "я showing тебе кое-что",
        "покажите документы",
        "скинься на подарок",
        "photograph",
        "фотоаппарат",
    ],
)
def test_does_not_match_substrings(text):
    assert is_photo_trigger(text) is False


@pytest.mark.parametrize("text", ["", None])
def test_empty_input(text):
    assert is_photo_trigger(text) is False
