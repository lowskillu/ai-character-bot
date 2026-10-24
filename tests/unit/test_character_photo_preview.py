import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from tgbot.keyboards.character_photo import get_character_photo_preview_keyboard
from tgbot.database.models import Profile
from tgbot.services.runware import async_runware_request, IImageInference


def test_character_photo_preview_keyboard_ru():
    kb = get_character_photo_preview_keyboard(lang="ru", profile_id=42)
    buttons = kb.inline_keyboard
    assert len(buttons) == 2
    assert buttons[0][0].text == "🔄 Перегенерировать"
    assert buttons[0][0].callback_data == "char_photo_regen:42"
    assert buttons[1][0].text == "👍 Мне всё нравится"
    assert buttons[1][0].callback_data == "char_photo_confirm:42"


def test_character_photo_preview_keyboard_en():
    kb = get_character_photo_preview_keyboard(lang="en", profile_id=99)
    buttons = kb.inline_keyboard
    assert len(buttons) == 2
    assert buttons[0][0].text == "🔄 Regenerate"
    assert buttons[0][0].callback_data == "char_photo_regen:99"
    assert buttons[1][0].text == "👍 Looks good!"
    assert buttons[1][0].callback_data == "char_photo_confirm:99"


def test_profile_reference_photo_url_attr():
    p = Profile(user_id=1, name="Test", reference_photo_url="https://example.com/ref.jpg")
    assert p.reference_photo_url == "https://example.com/ref.jpg"


@pytest.mark.asyncio
async def test_async_runware_request_with_reference_photo():
    req = IImageInference(positivePrompt="test", model="test_model")
    mock_sdk = MagicMock()
    mock_img = MagicMock()
    mock_img.imageURL = "https://example.com/result.jpg"
    mock_sdk.imageInference = AsyncMock(return_value=[mock_img])

    with patch("tgbot.services.runware.get_runware_sdk", AsyncMock(return_value=mock_sdk)):
        url = await async_runware_request(
            user_id=1,
            request_image=req,
            reference_photo_url="https://example.com/ref.jpg"
        )
        assert url == "https://example.com/result.jpg"
