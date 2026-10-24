"""The stage-2 invariant: no DB session is open while the LLM call is in flight.

This is the regression guard for the change that lifted the concurrency ceiling.
The handler used to wrap the whole exchange in one `_get_session()` block, so a
pooled connection and an open write transaction were pinned for the entire
OpenRouter round trip. With a pool of 20 that capped the bot at ~20 simultaneous
conversations regardless of how much CPU the box had.

Rather than stand up Postgres, this counts open sessions directly: any session
opened through AsyncORM increments a counter, and the fake LLM asserts the
counter is zero when it is called.
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest

from tests.fakes import FakeRedis
from tgbot.handlers import user as user_handler
from tgbot.services import chat as chat_service

PROFILE_ID = 99
USER_ID = 7


def make_redis() -> FakeRedis:
    """A Redis whose active-profile pointer already names PROFILE_ID.

    Deliberately a full fake rather than a stub with only ``get``: the handler
    also takes the per-user lock and spends a message quota, and a fake missing
    those methods would send every one of those calls down its error-handling
    branch while the test still passed.
    """
    return FakeRedis({f"active_profile:{USER_ID}": str(PROFILE_ID)})


class SessionTracker:
    def __init__(self):
        self.open = 0
        self.max_open = 0
        self.opened_total = 0
        self.open_during_llm = None


@dataclass
class FakeProfile:
    id: int = PROFILE_ID
    user_id: int = USER_ID
    name: str = "Саша"
    appearance: str = '{"hair": "light"}'
    body_type: str = '{"type": "slim"}'
    clothing: str = "sweater and jeans"
    personality: str = "cheerful"
    location: str = "cafe"
    role: str = "friend"
    description: str = None


class FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def all(self):
        return []


class FakeSession:
    async def execute(self, *_args, **_kwargs):
        return FakeResult(FakeProfile())

    def add(self, _obj):
        pass

    async def flush(self):
        pass


class FakeMessage:
    """Minimal aiogram Message stand-in."""

    def __init__(self, text="привет"):
        self.text = text
        self.from_user = type("U", (), {"id": USER_ID})()
        self.sent = []

    async def answer(self, text, **_kwargs):
        self.sent.append(text)
        return FakeSentMessage()


class FakeSentMessage:
    async def delete(self):
        return True


class FakeState:
    async def get_state(self):
        return None

    async def get_data(self):
        return {}


@pytest.fixture
def tracker(monkeypatch):
    t = SessionTracker()

    @asynccontextmanager
    async def tracking_session():
        t.open += 1
        t.opened_total += 1
        t.max_open = max(t.max_open, t.open)
        try:
            yield FakeSession()
        finally:
            t.open -= 1

    fake_orm_users = type("Repo", (), {"_get_session": staticmethod(tracking_session)})()
    monkeypatch.setattr(chat_service.AsyncORM, "users", fake_orm_users)

    # History reads and turn writes go through the same session; stub the SQL.
    async def fake_history(_session, _user_id, _profile_id):
        return [{"role": "user", "text": "раньше"}, {"role": "bot", "text": "ответ"}]

    async def fake_save(_session, *_args, **_kwargs):
        return None

    monkeypatch.setattr(chat_service, "get_profile_history_from_db", fake_history)
    monkeypatch.setattr(chat_service, "save_profile_message", fake_save)
    return t


async def test_tracker_actually_observes_open_sessions(tracker):
    """Self-check: proves the counter below is live.

    Without this, `open_during_llm == 0` could pass simply because the tracker
    never sees anything, and the real assertion would be vacuous.
    """
    assert tracker.open == 0
    async with chat_service.AsyncORM.users._get_session():
        assert tracker.open == 1, "the tracker is not wired up; the main test would be vacuous"
    assert tracker.open == 0


async def test_no_session_is_open_during_the_llm_call(tracker, monkeypatch):
    async def fake_llm(*_args, **_kwargs):
        # Sampled at the moment the network call happens.
        tracker.open_during_llm = tracker.open
        return "ответ модели"

    monkeypatch.setattr(user_handler, "generate_chat_response", fake_llm)

    message = FakeMessage()
    await user_handler.handle_text_with_profile(
        message, FakeState(), user={"language": "ru"}, redis=make_redis()
    )

    assert tracker.open_during_llm == 0, (
        "a DB session was held across the OpenRouter call — this is the bug that "
        "capped concurrency at one conversation per pool slot"
    )
    # Sanity: the test actually exercised the DB path rather than bailing early.
    assert tracker.opened_total >= 2, "expected a read transaction and a write transaction"
    assert tracker.max_open == 1, "transactions should not nest"


async def test_reply_is_delivered_before_the_turn_is_persisted(tracker, monkeypatch):
    """A failed write must not cost the user a reply they have already seen."""

    async def fake_llm(*_args, **_kwargs):
        return "ответ модели"

    async def exploding_save(*_args, **_kwargs):
        raise RuntimeError("database went away")

    monkeypatch.setattr(user_handler, "generate_chat_response", fake_llm)
    monkeypatch.setattr(chat_service, "save_turn", exploding_save)

    message = FakeMessage()
    await user_handler.handle_text_with_profile(
        message, FakeState(), user={"language": "ru"}, redis=make_redis()
    )

    assert any("ответ модели" in s for s in message.sent), "reply was lost when the write failed"


async def test_current_message_is_not_duplicated_into_history(tracker, monkeypatch):
    """generate_chat_response appends the current message itself.

    The handler used to append it as well, so the model saw it twice.
    """
    captured = {}

    async def fake_llm(_user_id, text, _lang, _name, _desc, history):
        captured["text"] = text
        captured["history"] = history
        return "ответ"

    monkeypatch.setattr(user_handler, "generate_chat_response", fake_llm)

    message = FakeMessage(text="новое сообщение")
    await user_handler.handle_text_with_profile(
        message, FakeState(), user={"language": "ru"}, redis=make_redis()
    )

    assert captured["text"] == "новое сообщение"
    assert all(turn["text"] != "новое сообщение" for turn in captured["history"])
