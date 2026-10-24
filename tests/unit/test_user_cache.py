"""The user cache in DatabaseMiddleware.

This middleware runs on every message and callback, so it was the most frequent
query in the bot: the breakpoint ramp showed the pool at 18 of 20 connections at
96 updates/s, a third of it re-reading a row that rarely changes.

Caching a user row is only safe if every write invalidates it, so most of these
tests are about staleness rather than about the happy path.
"""

import json


from tgbot.middlewares.database import (
    CACHE_TTL,
    DatabaseMiddleware,
    _cache_key,
    invalidate_user_cache,
)

USER_ID = 555


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value
        if ex:
            self.ttls[key] = ex
        return True

    async def delete(self, key):
        self.store.pop(key, None)
        return 1


class FakeUser:
    def __init__(self, uid=USER_ID, username="egor"):
        self.id = uid
        self.username = username
        self.is_bot = False


class FakeEvent:
    def __init__(self, username="egor"):
        self.from_user = FakeUser(username=username)


def _cached(username="egor", language="ru"):
    return json.dumps(
        {"id": USER_ID, "username": username, "language": language,
         "is_agreement_accepted": True}
    )


async def _call(mw, redis, event, db_calls, user_row=None):
    async def fake_load(user_id, username):
        db_calls.append((user_id, username))
        return user_row or {
            "id": user_id, "username": username,
            "language": "ru", "is_agreement_accepted": True,
        }

    mw._load_from_db = staticmethod(fake_load)

    captured = {}

    async def handler(_event, data):
        captured.update(data)
        return "handled"

    await mw(handler, event, {"redis": redis})
    return captured


async def test_cache_hit_skips_the_database():
    redis = FakeRedis()
    redis.store[_cache_key(USER_ID)] = _cached()
    db_calls = []

    data = await _call(DatabaseMiddleware(), redis, FakeEvent(), db_calls)

    assert db_calls == [], "served from cache, so no query should have run"
    assert data["user"]["language"] == "ru"


async def test_cache_miss_queries_and_then_populates():
    redis = FakeRedis()
    db_calls = []

    await _call(DatabaseMiddleware(), redis, FakeEvent(), db_calls)

    assert len(db_calls) == 1
    assert _cache_key(USER_ID) in redis.store
    assert redis.ttls[_cache_key(USER_ID)] == CACHE_TTL


async def test_changed_username_bypasses_the_cache():
    """Telegram usernames change; the new one has to reach the database."""
    redis = FakeRedis()
    redis.store[_cache_key(USER_ID)] = _cached(username="old_name")
    db_calls = []

    await _call(DatabaseMiddleware(), redis, FakeEvent(username="new_name"), db_calls)

    assert db_calls == [(USER_ID, "new_name")]


async def test_invalidate_forces_the_next_read_to_hit_the_database():
    """This is what stops a language change from taking a minute to appear."""
    redis = FakeRedis()
    redis.store[_cache_key(USER_ID)] = _cached(language="ru")

    await invalidate_user_cache(redis, USER_ID)

    db_calls = []
    await _call(DatabaseMiddleware(), redis, FakeEvent(), db_calls)
    assert len(db_calls) == 1


async def test_redis_down_falls_back_to_the_database():
    class BrokenRedis(FakeRedis):
        async def get(self, key):
            raise ConnectionError("redis is down")

        async def set(self, *a, **kw):
            raise ConnectionError("redis is down")

    db_calls = []
    data = await _call(DatabaseMiddleware(), BrokenRedis(), FakeEvent(), db_calls)

    assert len(db_calls) == 1
    assert data["user"]["id"] == USER_ID


async def test_no_redis_still_works():
    db_calls = []
    data = await _call(DatabaseMiddleware(), None, FakeEvent(), db_calls)
    assert len(db_calls) == 1
    assert data["user"]["id"] == USER_ID


async def test_corrupt_cache_entry_is_ignored():
    redis = FakeRedis()
    redis.store[_cache_key(USER_ID)] = "not json"
    db_calls = []

    await _call(DatabaseMiddleware(), redis, FakeEvent(), db_calls)
    assert len(db_calls) == 1


async def test_cached_payload_is_json_serialisable():
    """registered_at was a datetime and had to leave the payload."""
    redis = FakeRedis()
    await _call(DatabaseMiddleware(), redis, FakeEvent(), [])
    json.loads(redis.store[_cache_key(USER_ID)])


async def test_event_without_a_user_is_passed_through():
    class NoUser:
        from_user = None

    mw = DatabaseMiddleware()
    seen = {}

    async def handler(_event, data):
        seen["data"] = data
        return "ok"

    assert await mw(handler, NoUser(), {"redis": FakeRedis()}) == "ok"
    assert "user" not in seen["data"]
