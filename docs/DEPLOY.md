# Deployment

A checklist for the first rollout to a public server, and what to know about
running it.

## 1. Secrets

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # WEBHOOK_SECRET
python -c "import secrets; print(secrets.token_urlsafe(32))"   # REDIS_PASSWORD
```

| Variable | Without it |
|---|---|
| `BOT_TOKEN` | nothing works |
| `WEBHOOK_SECRET` | **the bot refuses to start.** Anyone who learns the webhook URL could post updates as any user_id — including an admin, which means `/admin` → broadcast to everyone and `/addpremium` |
| `REDIS_PASSWORD` | `--requirepass ""` → Redis without a password. The port is loopback-only, but FSM state and quota counters are open to anything on the host |
| `POSTGRES_PASSWORD` | — |
| `OPENROUTER_API_KEY`, `RUNWARE_API_KEY` | chat and pictures do not work |

`ALLOW_INSECURE_WEBHOOK=true` disables the secret check. Local development
only; never in production.

`.env` is in `.gitignore` and `.dockerignore`, so it never reaches the image.
To make sure it is really not tracked:

```bash
git ls-files | grep -c '^\.env$'
```

It must print `0`.

## 2. Webhook domain

`WEBHOOK_HOST` needs a permanent domain (a named Cloudflare tunnel, or an A
record + TLS). A `trycloudflare.com` quick tunnel is ephemeral: its hostname
changes on every restart, and after that Telegram delivers updates nowhere.

## 3. What is closed and why

**Only** `POST /webhook` is public.

`nginx/default.conf` restricts to private networks:

* the proxy to the local Bot API server (`location /`) — it runs with
  `--allow-unauthorized-updates`;
* serving downloaded files (`location /file/bot<token>/…`).

The bot does not need either through nginx: it talks to
`telegram-api-server:8081` directly over the compose network
(`TELEGRAM_API_BASE`).

`/webhook` is authenticated by the secret token, not an IP allowlist: requests
come from Cloudflare, not from Telegram's ranges, so an allowlist would either
break delivery or be so wide it proves nothing.

The Postgres and Redis ports are mapped to `127.0.0.1`.

After the first start, validate the nginx config (it has not been checked in a
container yet):

```bash
docker compose exec nginx nginx -t
```

## 4. Starting

```bash
docker compose up -d --build
```

The order is enforced by `depends_on`: Postgres and Redis pass their
healthchecks → the one-shot `migrations` job (`alembic upgrade head`) must exit
with 0 → the bot → nginx waits for the bot's `/healthz`.

Check:

```bash
docker compose ps
docker compose exec tg_bot python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:80/healthz').read())"
```

## 5. Capacity

Measurements are in [LOAD_TEST.md](LOAD_TEST.md).

| Variable | Default | When to change it |
|---|---|---|
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | 30 / 20 | `db_pool_checked_out` in `/metrics` approaches `db_pool_size`. This is the first thing to run out during a registration wave |
| `LLM_CONCURRENCY` | 256 | `requests_shed_total` grows while OpenRouter keeps up |
| `IMAGE_CONCURRENCY` | 8 | only if Runware raises your limit |
| `FREE_MESSAGE_LIMIT` / `PREMIUM_MESSAGE_LIMIT` | 25 / 200 | a product decision |

## 5.1 Models

All model ids and sampling parameters are env variables. The full list is in
`.env.example`.

| Variable | Default | What it is |
|---|---|---|
| `CHAT_MODEL` | `meta-llama/llama-3.3-70b-instruct` | character chat, OpenRouter |
| `PROMPT_MODEL` | `meta-llama/llama-3.3-70b-instruct` | builds the picture description, OpenRouter |
| `IMAGE_MODEL_ANIME` | `runware:101@1` | Runware model, also the fallback |
| `IMAGE_MODEL_REALISTIC` | `runware:101@1` | Runware model |
| `MAX_HISTORY_LENGTH` | 5 | how many past turns are sent to the model. The database keeps 10 — a separate knob: raising it improves continuity and costs tokens |

Changing a model does not need an image rebuild: edit `.env` and run
`docker compose up -d`. Rolling back a bad model works the same way.

**One picture costs two paid calls** (OpenRouter for the prompt + Runware for
the image); one chat message costs one.

Postgres `max_connections` is raised to 200 so the pool can grow.

## 6. Not verified yet — check on the first rollout

The unit tests start neither Postgres, Redis nor Telegram: everything external
is faked. So the following has only been checked by reading and compiling the
query, never against a real database under load:

| What | Where | How to check |
|---|---|---|
| History trimming with a single `DELETE … NOT IN (SELECT … LIMIT)` | `services/dialog_history.py:trim_profile_history` | Send 15 messages to one profile and make sure 10 are left and they are the newest |
| Keyset pagination of the broadcast | `database/orm.py:iter_all` | `/admin` → broadcast to a database of >500 users; make sure everyone got it, not only the first 500 |
| nginx config | `nginx/default.conf` | `docker compose exec nginx nginx -t` |
| Image build | `Dockerfile` | `docker compose build` |

The bench for the first two is described in [LOAD_TEST.md](LOAD_TEST.md) — it
runs a real Postgres in Docker.

## 7. Still open

These were left on purpose — they need the owner's decision, not a guess.

**Postgres backups.** There are none. Choose a location, a schedule and a
retention period. At minimum:

```bash
docker compose exec -T postgres_db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > backup-$(date +%F).sql.gz
```

**Resource limits in compose.** Not set: without knowing the server size, any
value risks an OOM kill instead of protection.

**History retention.** `delete_old_profile_messages()` (45 days) exists but is
never called. The table is already capped at 10 rows per profile
(`trim_profile_history`), so this is about a retention policy, not size: right
now an inactive user's chat is kept forever. Worth deciding deliberately.

**Dead schema objects.** The `users.welcome_sent` column (never read).
Dropping it is an irreversible migration, so it is left for the owner to decide.

**Key rotation.** `.env` has never been committed, but if the server or the
file was ever accessible to someone else, rotate `BOT_TOKEN`,
`OPENROUTER_API_KEY` and `RUNWARE_API_KEY`.

**The picture path has not been load-tested.** It needs a Runware stub.
`IMAGE_CONCURRENCY=8` is a guess, not tuned to Runware's real limits.
