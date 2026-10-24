"""The bot must only ever talk in one-to-one chats.

fallback_router matches *every* message, so before IsPrivate was attached,
adding the bot to a group made it answer everything said there — and every
free-text message became a paid LLM call.
"""

from types import SimpleNamespace

import pytest

from tgbot.filters.chat import IsPrivate


class FakeMessage:
    def __init__(self, chat_type):
        self.chat = SimpleNamespace(type=chat_type)


class FakeCallback:
    def __init__(self, msg):
        self.message = msg


@pytest.fixture
def patched(monkeypatch):
    """Swap the aiogram types IsPrivate isinstance-checks for the fakes above."""
    import tgbot.filters.chat as mod

    monkeypatch.setattr(mod, "Message", FakeMessage)
    monkeypatch.setattr(mod, "CallbackQuery", FakeCallback)
    return IsPrivate()


@pytest.mark.parametrize(
    ("chat_type", "expected"),
    [("private", True), ("group", False), ("supergroup", False), ("channel", False)],
)
async def test_messages_outside_private_chats_are_rejected(patched, chat_type, expected):
    assert await patched(FakeMessage(chat_type)) is expected


@pytest.mark.parametrize(
    ("chat_type", "expected"),
    [("private", True), ("group", False), ("supergroup", False)],
)
async def test_callbacks_follow_their_message(patched, chat_type, expected):
    assert await patched(FakeCallback(FakeMessage(chat_type))) is expected


async def test_callback_without_a_message_is_rejected(patched):
    """Inline-mode callbacks carry no message, so no private chat behind them."""
    assert await patched(FakeCallback(None)) is False
