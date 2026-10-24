"""Shared test doubles.

The per-file fakes in tests/unit/ are deliberately minimal — each documents the
exact Redis semantics the code under test depends on. This one is the opposite:
a reasonably complete in-memory Redis for handler tests, which touch several
Redis features at once (the user lock, the quota counters, the active-profile
pointer) and would otherwise silently exercise the error-handling path when a
method is missing.
"""


class FakeRedis:
    """In-memory stand-in covering the subset of redis.asyncio the bot uses.

    INCR/DECR are atomic here, exactly as the real server is: the read and the
    write happen with no await in between. Callers still interleave at every
    ``await``, which is the concurrency production code must survive.
    """

    def __init__(self, initial: dict | None = None):
        self.store: dict[str, object] = dict(initial or {})
        self.expires: dict[str, int] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value, ex=None, nx=False):
        if nx and key in self.store:
            return None
        self.store[key] = value
        if ex is not None:
            self.expires[key] = ex
        return True

    async def delete(self, key: str) -> int:
        existed = key in self.store
        self.store.pop(key, None)
        self.expires.pop(key, None)
        return int(existed)

    async def incr(self, key: str) -> int:
        self.store[key] = int(self.store.get(key, 0)) + 1
        return self.store[key]

    async def decr(self, key: str) -> int:
        self.store[key] = int(self.store.get(key, 0)) - 1
        return self.store[key]

    async def expire(self, key: str, ttl: int) -> bool:
        self.expires[key] = ttl
        return True

    async def ping(self) -> bool:
        return True
