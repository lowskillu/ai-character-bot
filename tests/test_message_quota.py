"""Message allowance on the chat path.

The premium and stats screens have advertised "25 сообщений/навсегда" and
"200/день" since the beginning, but nothing enforced either number: the free
tier was in practice an unlimited supply of paid LLM calls. These tests pin
both halves of the contract — the limit stops the user, and a turn that never
reached them is not charged for.
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest

from tests.fakes import FakeRedis
from tgbot.handlers import user as user_handler
from tgbot.services import chat as chat_service
from tgbot.services import quotas

PROFILE_ID = 99
USER_ID = 7


def make_redis() -> FakeRedis:
    return FakeRedis({f"active_profile:{USER_ID}": str(PROFILE_ID)})


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
    def scalar_one_or_none(self):
        return FakeProfile()

    def all(self):
        return []


class FakeSession:
    async def execute(self, *_args, **_kwargs):
        return FakeResult()

    def add(self, _obj):
        pass

    async def flush(self):
        pass


class FakeSentMessage:
    async def delete(self):
        return True


class FakeMessage:
    def __init__(self, text="привет"):
        self.text = text
        self.from_user = type("U", (), {"id": USER_ID})()
        self.sent = []

    async def answer(self, text, **_kwargs):
        self.sent.append(text)
        return FakeSentMessage()


class FakeState:
    async def get_state(self):
        return None

    async def get_data(self):
        return {}


@pytest.fixture
def orm(monkeypatch):
    @asynccontextmanager
    async def session():
        yield FakeSession()

    monkeypatch.setattr(
        chat_service.AsyncORM,
        "users",
        type("Repo", (), {"_get_session": staticmethod(session)})(),
    )

    async def fake_history(_session, _user_id, _profile_id):
        return []

    async def fake_save(_session, *_args, **_kwargs):
        return None

    monkeypatch.setattr(chat_service, "get_profile_history_from_db", fake_history)
    monkeypatch.setattr(chat_service, "save_profile_message", fake_save)


async def _send(redis, monkeypatch, reply="ответ модели", text="привет"):
    async def fake_llm(*_args, **_kwargs):
        return reply

    monkeypatch.setattr(user_handler, "generate_chat_response", fake_llm)
    message = FakeMessage(text=text)
    await user_handler.handle_text_with_profile(
        message, FakeState(), user={"language": "ru", "premium_level": 0}, redis=redis
    )
    return message


# --- the quota module itself ----------------------------------------------

async def test_free_tier_message_limit_is_a_lifetime_allowance():
    redis = FakeRedis()
    granted = sum(
        [
            await quotas.try_consume_message(redis, user_id=1, premium_level=0)
            for _ in range(quotas.FREE_MESSAGE_LIMIT + 5)
        ]
    )
    assert granted == quotas.FREE_MESSAGE_LIMIT

    key, _, _ = quotas.message_quota_key(1, 0)
    # A lifetime allowance must never expire, or it silently resets.
    assert key not in redis.expires


async def test_premium_message_key_expires_so_the_day_rolls_over():
    redis = FakeRedis()
    await quotas.try_consume_message(redis, user_id=2, premium_level=1)
    key, _, _ = quotas.message_quota_key(2, 1)
    assert redis.expires[key] == quotas.QUOTA_TTL


async def test_photo_and_message_quotas_use_separate_counters():
    """Spending photos must not eat into the message allowance, or vice versa."""
    redis = FakeRedis()
    await quotas.try_consume(redis, user_id=3, premium_level=0)
    used, _ = await quotas.get_message_usage(redis, user_id=3, premium_level=0)
    assert used == 0


# --- the handler ----------------------------------------------------------

async def test_chat_spends_one_message_per_delivered_reply(orm, monkeypatch):
    redis = make_redis()
    await _send(redis, monkeypatch)

    used, limit = await quotas.get_message_usage(redis, USER_ID, premium_level=0)
    assert (used, limit) == (1, quotas.FREE_MESSAGE_LIMIT)


async def test_chat_refuses_once_the_allowance_is_gone(orm, monkeypatch):
    redis = make_redis()
    key, limit, _ = quotas.message_quota_key(USER_ID, 0)
    redis.store[key] = limit  # already spent

    message = await _send(redis, monkeypatch)

    assert message.sent, "the user must be told why, not met with silence"
    assert "лимит" in message.sent[-1].lower()
    assert all("ответ модели" not in s for s in message.sent), "reply was generated anyway"


async def test_a_failed_turn_is_not_charged_for(orm, monkeypatch):
    """An LLM failure must not eat one of a free user's lifetime messages."""
    redis = make_redis()

    async def failing_llm(*_args, **_kwargs):
        return None

    monkeypatch.setattr(user_handler, "generate_chat_response", failing_llm)
    message = FakeMessage()
    await user_handler.handle_text_with_profile(
        message, FakeState(), user={"language": "ru", "premium_level": 0}, redis=redis
    )

    used, _ = await quotas.get_message_usage(redis, USER_ID, premium_level=0)
    assert used == 0, "the user paid for a reply they never received"


async def test_redis_outage_does_not_block_chat(orm, monkeypatch):
    """A quota that cannot be read must degrade to "allow", not to "no replies"."""

    class BrokenQuota(FakeRedis):
        async def incr(self, key):
            raise ConnectionError("redis is down")

    redis = BrokenQuota({f"active_profile:{USER_ID}": str(PROFILE_ID)})
    message = await _send(redis, monkeypatch)

    assert any("ответ модели" in s for s in message.sent)
