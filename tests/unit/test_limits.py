"""Load shedding: bounded concurrency and the per-user lock.

Before this the bot had no backpressure at all — every update became an
unbounded task and overload turned into unbounded latency instead of an honest
refusal.
"""

import asyncio

import pytest

from tgbot.services.limits import Busy, Limits, Overloaded, user_lock


class FakeRedis:
    """SET NX / DELETE, enough for the lock."""

    def __init__(self):
        self.store: dict[str, str] = {}

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def delete(self, key):
        self.store.pop(key, None)
        return 1


async def test_guard_allows_up_to_the_limit():
    limits = Limits()
    limits.llm = asyncio.Semaphore(2)
    held = []

    async def hold():
        async with limits.guard(limits.llm, "llm", timeout=0.05):
            held.append(1)
            await asyncio.sleep(0.1)

    await asyncio.gather(hold(), hold())
    assert len(held) == 2


async def test_guard_sheds_instead_of_queueing():
    """The third caller is refused rather than parked behind the other two."""
    limits = Limits()
    limits.llm = asyncio.Semaphore(2)

    async def hold():
        async with limits.guard(limits.llm, "llm", timeout=0.05):
            await asyncio.sleep(0.5)

    async def third():
        async with limits.guard(limits.llm, "llm", timeout=0.05):
            return "got in"

    results = await asyncio.gather(hold(), hold(), third(), return_exceptions=True)
    assert isinstance(results[2], Overloaded)


async def test_guard_releases_the_slot_after_an_error():
    limits = Limits()
    limits.llm = asyncio.Semaphore(1)

    with pytest.raises(ValueError):
        async with limits.guard(limits.llm, "llm", timeout=0.05):
            raise ValueError("boom")

    # The slot must be free again, or one failure would leak capacity forever.
    async with limits.guard(limits.llm, "llm", timeout=0.05):
        pass


async def test_user_lock_blocks_a_second_concurrent_request():
    redis = FakeRedis()

    async with user_lock(redis, 42):
        with pytest.raises(Busy):
            async with user_lock(redis, 42):
                pass


async def test_user_lock_releases_on_exit():
    redis = FakeRedis()
    async with user_lock(redis, 42):
        pass
    async with user_lock(redis, 42):
        pass  # must not raise


async def test_user_lock_releases_even_when_the_handler_raises():
    redis = FakeRedis()
    with pytest.raises(RuntimeError):
        async with user_lock(redis, 42):
            raise RuntimeError("handler blew up")
    async with user_lock(redis, 42):
        pass


async def test_different_users_do_not_block_each_other():
    redis = FakeRedis()
    async with user_lock(redis, 1):
        async with user_lock(redis, 2):
            pass


async def test_redis_failure_does_not_block_the_bot():
    """A Redis outage must degrade to "no locking", not to "no replies"."""

    class BrokenRedis(FakeRedis):
        async def set(self, *a, **kw):
            raise ConnectionError("redis is down")

    entered = False
    async with user_lock(BrokenRedis(), 42):
        entered = True
    assert entered
