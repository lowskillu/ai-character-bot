"""A declined image request is never retried.

Sending the same request again after the model said no looks like an attempt to
get past the model's own rules. The bot goes straight to a neutral scene built
from the profile instead, and the user's text is left out of it.
"""

from contextlib import asynccontextmanager

import pytest

from tgbot.services import prompt_formation

PROFILE = {
    "profile_id": None,
    "hair": "brown",
    "skin": "olive skin",
    "clothing": "Loose hoodie and track pants",
    "location": "park",
    "style": "anime",
    "language": "en",
}


class FakeResponse:
    def __init__(self, content):
        self._content = content

    def raise_for_status(self):
        return None

    async def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


class FakeSession:
    def __init__(self, content):
        self.content = content
        self.calls = 0

    @asynccontextmanager
    async def post(self, *_args, **_kwargs):
        self.calls += 1
        yield FakeResponse(self.content)


async def _run(monkeypatch, model_answer, request="show something odd"):
    session = FakeSession(model_answer)

    async def fake_get_http_session():
        return session

    async def get_profile(_uid):
        return dict(PROFILE)

    monkeypatch.setattr(prompt_formation, "get_http_session", fake_get_http_session)
    result = await prompt_formation.generate_photo_prompt(
        text=request, user_id=1, get_user_profile=get_profile, user_states={}, history=[]
    )
    return result, session


@pytest.mark.parametrize("answer", ["I'm sorry, I cannot help with that.", "Извините, не могу."])
async def test_refusal_is_not_retried_and_falls_back(monkeypatch, answer):
    result, session = await _run(monkeypatch, answer)
    assert session.calls == 1, "a declined request was sent to the model again"
    assert result == prompt_formation.safe_fallback_prompt(PROFILE)


async def test_fallback_never_contains_the_users_text(monkeypatch):
    result, _ = await _run(monkeypatch, "I cannot do that.", request="UNIQUE-REQUEST-MARKER")
    assert "UNIQUE-REQUEST-MARKER" not in result


async def test_a_normal_answer_is_used_as_is(monkeypatch):
    answer = "Character: brown hair\nScene: portrait, reading a book"
    result, session = await _run(monkeypatch, answer)
    assert session.calls == 1
    assert result == answer


async def test_empty_answer_gives_none(monkeypatch):
    result, session = await _run(monkeypatch, "   ")
    assert result is None
    assert session.calls == 1
