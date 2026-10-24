"""Premium expiry and user resolution.

The expiry rule had four hand-written copies and three of them ignored
``premium_until`` entirely — a lapsed subscriber kept the 50-photos/day quota
and four profile slots, and the stats screen told them they were still active.

Username resolution matters because users.username is deliberately NOT unique:
Telegram frees names and reassigns them, so a dormant row can keep a @name that
somebody else now owns.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from tgbot.services import premium


def user(level=0, until=None):
    return SimpleNamespace(id=1, premium_level=level, premium_until=until)


PAST = datetime.utcnow() - timedelta(days=1)
FUTURE = datetime.utcnow() + timedelta(days=30)


# --- effective_level -------------------------------------------------------

@pytest.mark.parametrize(
    ("obj", "expected", "why"),
    [
        (None, 0, "no user at all"),
        (user(0, None), 0, "never subscribed"),
        (user(0, FUTURE), 0, "level 0 wins over a future date"),
        (user(1, FUTURE), 1, "active subscription"),
        (user(2, FUTURE), 2, "level is carried through, not flattened to 1"),
        (user(1, None), 1, "NULL expiry is an open-ended grant, not an expired one"),
        (user(1, PAST), 0, "expired — this is the case the raw column missed"),
    ],
)
def test_effective_level(obj, expected, why):
    assert premium.effective_level(obj) == expected, why


def test_is_active_agrees_with_effective_level():
    assert premium.is_active(user(1, FUTURE)) is True
    assert premium.is_active(user(1, PAST)) is False
    assert premium.is_active(None) is False


def test_expiry_is_exclusive_at_the_boundary():
    """A grant that ended exactly now is over, not still running."""
    assert premium.effective_level(user(1, datetime.utcnow())) == 0


def test_a_missing_column_does_not_explode():
    """effective_level is called on rows loaded in several different ways."""
    assert premium.effective_level(SimpleNamespace(id=1)) == 0


# --- resolve_user ----------------------------------------------------------

class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class FakeSession:
    def __init__(self, rows=(), by_id=None):
        self.rows = list(rows)
        self.by_id = by_id or {}
        self.get_calls = []

    async def execute(self, _q):
        return FakeResult(self.rows)

    async def get(self, _model, pk):
        self.get_calls.append(pk)
        return self.by_id.get(pk)


async def test_numeric_identifier_is_looked_up_by_primary_key():
    session = FakeSession(by_id={42: user(1, FUTURE)})
    found = await premium.resolve_user(session, "42")
    assert found is not None
    assert session.get_calls == [42], "a numeric id must not be treated as a username"


async def test_username_is_matched_without_the_at_sign():
    target = user(1, FUTURE)
    assert await premium.resolve_user(FakeSession([target]), "@egor") is target


async def test_unknown_username_returns_none():
    assert await premium.resolve_user(FakeSession([]), "nobody") is None


async def test_a_shared_username_is_reported_rather_than_guessed():
    """Two rows can genuinely hold one @name; picking one silently is wrong."""
    a, b = user(0), user(0)
    a.id, b.id = 10, 20
    with pytest.raises(premium.AmbiguousUsername) as excinfo:
        await premium.resolve_user(FakeSession([a, b]), "recycled")
    assert excinfo.value.user_ids == [10, 20]
    assert "recycled" in str(excinfo.value)


# --- grant_premium ---------------------------------------------------------

class GrantSession(FakeSession):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.flushed = False

    async def flush(self):
        self.flushed = True


async def test_grant_sets_level_and_expiry_and_returns_the_user():
    target = user(0, None)
    session = GrantSession([target])
    result = await premium.grant_premium(session, "egor", level=1, days=30)

    assert result is target
    assert target.premium_level == 1
    assert target.premium_until > datetime.utcnow() + timedelta(days=29)
    assert session.flushed, "the change was never written"
    # And the grant it just made must read back as active.
    assert premium.effective_level(target) == 1


async def test_grant_to_an_unknown_user_returns_none_without_writing():
    session = GrantSession([])
    assert await premium.grant_premium(session, "nobody", 1, 30) is None
    assert not session.flushed


async def test_grant_propagates_ambiguity_instead_of_granting_to_a_random_row():
    a, b = user(0), user(0)
    a.id, b.id = 1, 2
    with pytest.raises(premium.AmbiguousUsername):
        await premium.grant_premium(GrantSession([a, b]), "recycled", 1, 30)
    assert a.premium_level == 0 and b.premium_level == 0, "someone got premium by accident"
