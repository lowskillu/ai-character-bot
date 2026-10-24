# Load tests

Test bench, results and the defects they found. Runs from 2026-08-07/08.

## First test: the synchronous version

The first version of the bot processed updates synchronously: while one update
was waiting for a response (from the database or the model), all the others
waited in line.

To test it I used a third-party traffic service that sent the bot about 6,000
`/start` commands from different accounts.

| version | time to process 6,000 `/start` |
|---|---|
| synchronous | about 4 hours |
| asynchronous (aiohttp) | about 3 minutes |

The synchronous version did not crash and barely used the CPU (up to 3 %);
every request simply waited for the previous one. My own `/start`, sent during
the test, got a reply after about 4 hours.

The asynchronous result was limited by my machine's resources and the speed of
the service, not by the bot's code. That is why I moved on to the reproducible
stub-based tests described below.

## Test bench

| Component | What was used |
|---|---|
| Postgres | `postgres:16-alpine` in Docker, schema via `alembic upgrade head` |
| Redis | `redis:7-alpine` in Docker |
| Telegram Bot API | stub ([tests/load/stubs.py](../tests/load/stubs.py)), 20–50 ms latency |
| OpenRouter | stub, `lognormal(1.6, 0.6)` — median ≈5 s, p99 ≈20 s |
| Driver | [tests/load/driver.py](../tests/load/driver.py), constant arrival rate |
| Ramp | [tests/load/breakpoint.py](../tests/load/breakpoint.py) |

The driver uses an **open model**: it keeps the target rate no matter how much
the bot slows down. A closed model would throttle itself and hide exactly the
backpressure being measured.

The Bot API stub is the measurement point: it records the moment of
`sendMessage`, which is when the user would actually have seen the reply.

**Everything runs on one machine** — the bot, both stubs, the driver and both
databases share 20 cores. At the top steps the driver competes with the bot for
CPU, so the numbers are more pessimistic than a dedicated server would give.

## Target scenario: 200 users, 8 msg/s

```
960 updates → 960 replies (100 %), 0 errors
p50 5.05 s against a 5.0 s LLM stub median — the bot adds ~50 ms
Postgres connections: at most 6 of a pool of 10
idle in transaction: max 0
```

It was also checked that the test **can catch the opposite**: with the old
shape restored (a DB session held across the LLM call) the same load gave
396/480 delivered, 564 pool errors and 20 connections parked in open
transactions.

## Ramp to failure

Two runs of the same ramp. The difference between the profiles matters and
explains the gap:

**Returning users** (500 users sending repeatedly):

| load | delivered | p50 | pg | idle_tx |
|---|---|---|---|---|
| 8/s | 100 % | 6.02 | 4 | 1 |
| 24/s | 100 % | 9.76 | 6 | 1 |
| 48/s | 100 % | 10.63 | 10 | 0 |
| 96/s | 100 % | 10.67 | 18 | 5 |
| 160/s | **100 %** | 10.87 | 19 | 14 |

**No breaking point found up to 160 msg/s — 20× the target.**

**All users new** (`--unique-users`, every message is a registration):

| load | delivered | p50 | pg | idle_tx |
|---|---|---|---|---|
| 8/s | 100 % | 5.44 | 6 | 0 |
| 24/s | 100 % | 4.94 | 7 | 2 |
| 48/s | 100 % | 5.16 | 21 | 12 |
| 96/s | **66 %** | 9.83 | 22 | 18 |
| 160/s | **39 %** | 12.75 | 21 | 18 |

Here p50 stays at the LLM median up to 48/s — the bot adds nothing measurable
to the model's response time. Failure starts at 96/s, and the limit is the
**Postgres pool**: a new user is a get-or-create, i.e. an INSERT, not a SELECT.

**Practical takeaway:** the bottleneck is not regular traffic but a
**registration wave** — the first day after a release. The user cache cannot
help there by design; the fix is pool size. Watch `db_pool_checked_out` in
`/metrics`.

## Defects found

### 1. Silence instead of a reply when infrastructure fails

At 96/s **34 % of users got nothing at all** — neither a reply nor an error
message, with zero HTTP errors. `load_chat_context` was called without a
handler: the pool timeout propagated past the handler, aiogram logged it, and
that was it.

Silence is the worst outcome: the user cannot tell whether to wait or retry,
so they retry, adding load exactly when there is no capacity for it. Fixed in
three places, including `DatabaseMiddleware`, where the timeout aborted the
update **before** any handler ran.

### 2. Unbounded Redis pool growth

redis-py leaves `max_connections` effectively unlimited and opens a socket for
every concurrent command. At 160 msg/s that meant **993 open connections**,
against a default `maxclients` of 10000 and a memory cost on both ends.

After bounding the pool: **993 → 201**.

### 3. A two-second Redis timeout silently took the bot down

A textbook `socket_connect_timeout=2` left no margin: on a host where opening a
connection took ~2.05 s (IPv6 → IPv4 fallback), **every** Redis operation
failed. And because the webhook acknowledges before processing, the bot
answered 200 to every update and lost all of them.

Measured variants:

| setting | result |
|---|---|
| no timeouts | OK (2.05 s) |
| `connect_timeout=2` | **FAIL** |
| `connect_timeout=5` | OK |
| `socket_timeout=2` | **FAIL** |
| relaxed to 5 s | OK |

Redis commands themselves are sub-millisecond, so a generous ceiling costs
nothing and only catches a genuinely hung connection. `/healthz` detects this
failure — which was the point of the endpoint.

## Not tested

- **The picture generation path was not load-tested at all.** It needs a
  Runware stub (their websocket protocol). The limit of 8 parallel generations
  is a guess, not tuned to Runware's real limits.
- The stubs model latency, but not 429s, dropped connections or model
  variability.
- Runs last 30 seconds. Leaks that show up over hours are not caught this way.
- `http_errors` at 160/s (~1000) is almost certainly the test bench's
  connection-accept limit, not the bot's.

## How to reproduce

```bash
docker run -d --name loadtest-pg -e POSTGRES_DB=migtest -e POSTGRES_USER=migtest -e POSTGRES_PASSWORD=migtest -p 127.0.0.1:5432:5432 postgres:16-alpine
docker run -d --name loadtest-redis -p 127.0.0.1:6379:6379 redis:7-alpine
alembic upgrade head
python -m tests.load.stubs
python bot.py
python -m tests.load.breakpoint
```

The bot needs `TELEGRAM_API_BASE=http://127.0.0.1:8099`,
`OPENROUTER_API_URL=http://127.0.0.1:8098/chat/completions`, `WEBHOOK_PORT=8080`
and a **deliberately fake `BOT_TOKEN`** — otherwise `set_webhook` would point
real Telegram traffic at the test machine.

To measure capacity (rather than load shedding), raise `LLM_CONCURRENCY` above
`rate × median_latency`.
