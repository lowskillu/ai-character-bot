"""Load driver: constant arrival rate against the bot's webhook.

Open model on purpose. It keeps offering the target rate no matter how slow the
bot gets, which is what real users do. A closed model (each virtual user waits
for its own reply before sending again) throttles itself and hides exactly the
backpressure we are trying to measure.

End-to-end latency is measured at the stub Bot API: the moment it receives the
sendMessage carrying the model's reply is the moment a user would have seen it.

The headline metric is `idle_in_transaction`. That is the direct evidence for
the stage-2 change: it counts Postgres connections parked inside an open
transaction. Holding one across the LLM call is what capped concurrency.

    python -m tests.load.driver --users 200 --rate 8 --duration 120
"""

import argparse
import asyncio
import json
import statistics
import time

import aiohttp
import asyncpg
import redis.asyncio as aioredis

MESSAGES = [
    "привет как дела",
    "расскажи что-нибудь",
    "чем занимаешься",
    "посоветуй книгу",
    "что нового",
]


async def seed(pg_dsn: str, redis_url: str, users: int) -> None:
    """Create users + one profile each, and mark the profile active in Redis."""
    conn = await asyncpg.connect(pg_dsn)
    try:
        await conn.execute("DELETE FROM profile_message_history")
        await conn.execute("DELETE FROM profiles")
        await conn.execute("DELETE FROM users WHERE id >= 900000000")

        await conn.executemany(
            "INSERT INTO users (id, username, welcome_sent, style, premium_level, language)"
            " VALUES ($1, $2, false, 'anime', 0, 'ru')",
            [(900000000 + i, f"loadtest{i}", ) for i in range(users)],
        )
        rows = await conn.fetch(
            "INSERT INTO profiles (user_id, name, style, appearance, body_type,"
            " clothing, personality, location, role)"
            " SELECT id, 'Саша', 'anime', '{\"hair\":\"light\"}', '{\"type\":\"slim\"}',"
            " 'sweater and jeans', 'cheerful', 'cafe', 'friend'"
            " FROM users WHERE id >= 900000000 RETURNING id, user_id"
        )
    finally:
        await conn.close()

    r = aioredis.from_url(redis_url, decode_responses=True)
    try:
        pipe = r.pipeline()
        for row in rows:
            pipe.set(f"active_profile:{row['user_id']}", row["id"])
        await pipe.execute()
    finally:
        await r.aclose()

    print(f"seeded {users} users with an active profile each", flush=True)


async def sample_metrics(pg_dsn: str, redis_url: str, stop: asyncio.Event, out: dict):
    """Poll the things that prove (or disprove) the concurrency fix."""
    conn = await asyncpg.connect(pg_dsn)
    r = aioredis.from_url(redis_url, decode_responses=True)
    try:
        while not stop.is_set():
            total, idle_tx = await conn.fetchrow(
                "SELECT count(*) FILTER (WHERE state IS NOT NULL),"
                "       count(*) FILTER (WHERE state = 'idle in transaction')"
                "  FROM pg_stat_activity WHERE datname = current_database()"
            )
            clients = int((await r.info("clients"))["connected_clients"])
            out["pg_total"].append(total)
            out["idle_in_transaction"].append(idle_tx)
            out["redis_clients"].append(clients)
            try:
                await asyncio.wait_for(stop.wait(), timeout=0.5)
            except asyncio.TimeoutError:
                pass
    finally:
        await conn.close()
        await r.aclose()


async def fire(session, url, secret, uid, seq, sent, errors):
    headers = {"X-Telegram-Bot-Api-Secret-Token": secret} if secret else {}
    update = {
        "update_id": seq,
        "message": {
            "message_id": seq,
            "date": int(time.time()),
            "chat": {"id": uid, "type": "private"},
            "from": {"id": uid, "is_bot": False, "first_name": "L"},
            "text": MESSAGES[seq % len(MESSAGES)],
        },
    }
    sent.setdefault(uid, []).append(time.time())
    try:
        async with session.post(url, json=update, headers=headers) as resp:
            if resp.status != 200:
                errors.append(resp.status)
    except Exception as e:  # noqa: BLE001
        errors.append(repr(e))


async def run(args) -> int:
    pg_dsn = args.pg_dsn
    total = int(args.rate * args.duration)

    # One virtual user per message. With several messages in flight for the same
    # user, replies come back out of order (the latency distribution is
    # lognormal) while the matching below is FIFO, which systematically inflates
    # the measured latency as the rate climbs -- an artefact of the harness, not
    # the bot. One message per user makes the pairing exact.
    if args.unique_users:
        args.users = total

    await seed(pg_dsn, args.redis_url, args.users)

    async with aiohttp.ClientSession() as s:
        await s.post(f"{args.stub_url}/reset")

    metrics = {"pg_total": [], "idle_in_transaction": [], "redis_clients": []}
    stop = asyncio.Event()
    sampler = asyncio.create_task(sample_metrics(pg_dsn, args.redis_url, stop, metrics))

    sent: dict[int, list[float]] = {}
    errors: list = []
    interval = 1.0 / args.rate

    print(f"firing {args.rate}/s for {args.duration}s ({total} updates)", flush=True)
    started = time.time()
    connector = aiohttp.TCPConnector(limit=0)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = []
        for seq in range(total):
            uid = 900000000 + (seq % args.users)
            tasks.append(asyncio.create_task(
                fire(session, args.webhook_url, args.secret, uid, seq + 1, sent, errors)
            ))
            # Open model: the schedule does not slip when the bot slows down.
            target = started + (seq + 1) * interval
            drift = target - time.time()
            if drift > 0:
                await asyncio.sleep(drift)
        await asyncio.gather(*tasks)

    print("all updates delivered, waiting for replies to drain...", flush=True)
    await asyncio.sleep(args.drain)
    stop.set()
    await sampler

    async with aiohttp.ClientSession() as s:
        async with s.get(f"{args.stub_url}/stats") as resp:
            stats = await resp.json()

    # A reply is any sendMessage that is not the "typing" placeholder.
    replies = [
        r for r in stats["replies"]
        if "Печатает" not in r["text"] and "Typing" not in r["text"]
    ]
    # FIFO match per user: a user sends several messages during the run, so
    # pair each reply with that user's oldest still-unanswered send rather than
    # only remembering the latest one.
    pending = {uid: list(ts) for uid, ts in sent.items()}
    latencies = []
    for r in sorted(replies, key=lambda x: x["ts"]):
        q = pending.get(r["chat_id"])
        if q:
            latencies.append(r["ts"] - q.pop(0))

    result = {
        "updates_sent": total,
        "replies_delivered": len(replies),
        "http_errors": len(errors),
        "counters": stats["counters"],
        "latency_p50": round(statistics.median(latencies), 3) if latencies else None,
        "latency_p95": round(sorted(latencies)[int(len(latencies) * 0.95)], 3) if latencies else None,
        "latency_max": round(max(latencies), 3) if latencies else None,
        "pg_connections_max": max(metrics["pg_total"], default=0),
        "idle_in_transaction_max": max(metrics["idle_in_transaction"], default=0),
        "idle_in_transaction_avg": round(
            statistics.mean(metrics["idle_in_transaction"]), 2
        ) if metrics["idle_in_transaction"] else 0,
        "redis_clients_first": metrics["redis_clients"][0] if metrics["redis_clients"] else 0,
        "redis_clients_last": metrics["redis_clients"][-1] if metrics["redis_clients"] else 0,
        "redis_clients_max": max(metrics["redis_clients"], default=0),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--users", type=int, default=200)
    p.add_argument("--rate", type=float, default=8.0, help="updates per second")
    p.add_argument("--duration", type=int, default=120, help="seconds")
    p.add_argument("--drain", type=int, default=60, help="seconds to wait for replies")
    p.add_argument(
        "--unique-users", action="store_true",
        help="one user per message, so reply/send pairing is exact",
    )
    p.add_argument("--webhook-url", default="http://127.0.0.1:8080/webhook")
    p.add_argument("--stub-url", default="http://127.0.0.1:8099")
    p.add_argument("--secret", default="loadtest")
    p.add_argument("--pg-dsn", default="postgresql://migtest:migtest@127.0.0.1:5432/migtest")
    # db 0: Config.redis.dsn() defaults to database 0, and both the FSM storage
    # and the active-profile pointer live there.
    p.add_argument("--redis-url", default="redis://127.0.0.1:6379/0")
    raise SystemExit(asyncio.run(run(p.parse_args())))
