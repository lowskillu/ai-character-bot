"""Photo quota accounting.

The quota used to be read-then-act: check the counter, generate the image, then
increment. Concurrent requests all read the same pre-limit value and sailed
through. These tests force interleaving so that shape fails.
"""

import asyncio


from tgbot.services import quotas


class FakeRedis:
    """Minimal async Redis stand-in.

    INCR and DECR are atomic here, exactly as the real server is: the read and
    the write happen with no await between them. Callers still interleave at
    every ``await``, which is the concurrency the production code must survive.

    Getting this wrong matters. An earlier version of this fake yielded *inside*
    incr, modelling a non-atomic counter that Redis does not have; every
    concurrent caller then read 0 and the test failed against correct code.
    """

    def __init__(self):
        self.store: dict[str, int] = {}
        self.expires: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    async def decr(self, key: str) -> int:
        self.store[key] = self.store.get(key, 0) - 1
        return self.store[key]

    async def expire(self, key: str, ttl: int) -> bool:
        await asyncio.sleep(0)
        self.expires[key] = ttl
        return True

    async def get(self, key: str):
        await asyncio.sleep(0)
        return self.store.get(key)


async def test_free_tier_allows_exactly_two():
    redis = FakeRedis()
    results = [await quotas.try_consume(redis, user_id=1, premium_level=0) for _ in range(5)]
    assert results == [True, True, False, False, False]


async def test_premium_tier_allows_fifty():
    redis = FakeRedis()
    granted = sum(
        [await quotas.try_consume(redis, user_id=1, premium_level=1) for _ in range(60)]
    )
    assert granted == quotas.PREMIUM1_LIMIT


async def test_concurrent_requests_cannot_exceed_the_limit():
    """50 simultaneous requests against a limit of 2 must yield exactly 2."""
    redis = FakeRedis()
    results = await asyncio.gather(
        *[quotas.try_consume(redis, user_id=7, premium_level=0) for _ in range(50)]
    )
    assert sum(results) == quotas.DEFAULT_LIMIT


async def test_rejected_requests_do_not_inflate_the_counter():
    """An over-limit attempt hands its reservation back."""
    redis = FakeRedis()
    for _ in range(10):
        await quotas.try_consume(redis, user_id=3, premium_level=0)

    used, limit = await quotas.get_usage(redis, user_id=3, premium_level=0)
    assert (used, limit) == (2, 2)


async def test_release_frees_a_slot_after_failed_generation():
    redis = FakeRedis()
    assert await quotas.try_consume(redis, user_id=4, premium_level=0) is True
    assert await quotas.try_consume(redis, user_id=4, premium_level=0) is True
    assert await quotas.try_consume(redis, user_id=4, premium_level=0) is False

    # Generation failed for one of them -> slot returns to the pool.
    await quotas.release(redis, user_id=4, premium_level=0)
    assert await quotas.try_consume(redis, user_id=4, premium_level=0) is True


async def test_premium_key_gets_a_ttl_but_free_key_does_not():
    redis = FakeRedis()
    await quotas.try_consume(redis, user_id=5, premium_level=1)
    await quotas.try_consume(redis, user_id=6, premium_level=0)

    premium_key, _, _ = quotas.quota_key(5, 1)
    free_key, _, _ = quotas.quota_key(6, 0)

    assert redis.expires[premium_key] == quotas.QUOTA_TTL
    # The free tier is a lifetime allowance, so it must never expire.
    assert free_key not in redis.expires


async def test_release_never_raises_when_redis_is_down():
    class BrokenRedis(FakeRedis):
        async def decr(self, key):
            raise ConnectionError("redis is down")

    await quotas.release(BrokenRedis(), user_id=1, premium_level=0)
