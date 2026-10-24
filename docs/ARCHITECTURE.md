# AI Character Bot architecture

This document describes the **current** state of the code and the target
structure it is moving towards. The rollout checklist is in
[DEPLOY.md](DEPLOY.md), measurements are in [LOAD_TEST.md](LOAD_TEST.md).

## What the bot does

A Telegram bot with AI characters. Two heavy flows:

| Flow | Path | Cost |
|---|---|---|
| **Chat** | text → active profile + last 10 messages from Postgres → OpenRouter (`meta-llama/llama-3.3-70b-instruct`) → reply → 2 history rows | 1 LLM call, median ~5 s |
| **Picture** | trigger word → profile → OpenRouter builds the image prompt → Runware over websocket → picture | 2 external calls, 10–40 s |

Plus: a character-creation wizard (FSM), inline menus, ru/en, premium tiers,
an admin broadcast.

## How an update flows

```
Telegram → nginx:80 → tg_bot:80/webhook   ← the only public path
                          │
                          ├─ GracefulRequestHandler checks secret_token
                          ├─ answers 200 in ~2 ms
                          └─ asyncio.create_task(handling)
                                  │
                                  ├─ IsPrivate (Dispatcher filter)  one-to-one chats only
                                  ├─ AntiDuplicateMiddleware   SET NX on update_id
                                  ├─ ConfigMiddleware          injects config + redis
                                  ├─ DatabaseMiddleware        get-or-create the user (cached)
                                  ├─ DeveloperMiddleware       admins only in dev mode
                                  └─ routers_list, in order
```

**Key fact:** aiogram already answers Telegram immediately and handles the
update in a background task (`handle_in_background=True` by default). The
bottleneck is not the webhook but the Postgres connection pool.

---

## Repository root

| File | Responsibility |
|---|---|
| `bot.py` | Entry point and lifecycle. Builds Bot/Dispatcher/Redis/engine, sets up the webhook and middleware, waits for a stop signal, shuts everything down in order. `GracefulRequestHandler` waits for in-flight updates. |
| `pyproject.toml` | Dependencies (direct ones only) + ruff/mypy/pytest config. Replaced `requirements.txt`. |
| `Dockerfile` | Multi-stage build on `python:3.11-slim`. The builder installs dependencies into a venv; the runtime gets only the venv + code and runs as non-root. |
| `docker-compose.yml` | Production stack: nginx, telegram-api-server, postgres, redis, one-shot migrations, the bot. DB/Redis ports on loopback only, log rotation, healthchecks. |
| `alembic.ini` | Alembic config. `sqlalchemy.url` is deliberately empty — the URL is built from the environment in `migrations/env.py`. |
| `.env.example` | Template for all 20+ environment variables. |
| `.dockerignore` | Keeps `.env`, `.git`, caches and tests out of the image. |
| `nginx/default.conf` | Only `/webhook` is public (keep-alive to the bot). The Bot API proxy and file server are limited to private networks: the server runs with `--allow-unauthorized-updates`, and the bot reaches it directly over the compose network. Masks the token in logs. |
| `migrations/env.py` | Alembic environment. Always overrides the URL from `load_config()` and swaps `asyncpg` for `psycopg` in online mode. |
| `migrations/versions/` | Schema revisions: baseline + indexes/FKs/dropping username uniqueness + reference picture URL. |
| `conftest.py` | Puts the repository root on `sys.path`; otherwise `pytest` (unlike `python -m pytest`) cannot find `tests.fakes`. |

## `tgbot/` — the bot

### `tgbot/database/` — data layer

| File | Responsibility |
|---|---|
| `database.py` | `Base` — SQLAlchemy declarative base with a generic `__repr__`. |
| `models.py` | Three tables: `User` (language, style, premium, picture settings), `Profile` (the character: appearance/build/clothing/personality/location/role), `ProfileMessageHistory` (chat history). |
| `orm.py` | Generic `CRUDBase[T]` + repositories + the static `AsyncORM` registry. `_get_session()` is the single place where a session **and a transaction** are opened. `iter_all()` — keyset pagination for the broadcast. |

> **Known issue:** `Profile` is the only model without a repository; it is
> accessed through free functions in `services/profile.py`. Two competing
> data-access styles.

### `tgbot/handlers/` — handlers

Registration order is set in `__init__.py` and **matters**: the first router
with a matching handler wins.

| File | Responsibility |
|---|---|
| `__init__.py` | Ordered `routers_list`, specific to general. |
| `admin.py` | `/admin`, text/photo broadcast. Admin filter on message **and** callback. |
| `menu.py` | `/menu` and all submenus: language, profiles, premium, style, stats, reset, editing. The largest file. |
| `premium_grant.py` | `/addpremium <level> <username|id> <days>`. |
| `customization.py` | Character wizard: optional channel subscription gate, name, random character, preview, saving. |
| `customization_body.py` | Build submenu: build type, height. |
| `customization_options.py` | Clothing, personality, location, role. Four modules with structurally identical handlers (86–92 %) collapsed into one `SCREENS` table. |
| `visual_vnesnost.py` | Appearance submenu: hair, skin tone, style. Owns the `customize_appearance` callback. |
| `photo.py` | Picture trigger (word boundaries, outside the FSM only) + picture settings. |
| `dialogue_continiur.py` | Switching profiles: show the last 4 messages, "start over" / "continue". |
| `style.py` | The "Start 🚀" button — clears the state and shows the profile list. |
| `user.py` | Onboarding (`/start`, language, agreement) and the **main LLM chat loop**. |
| `fallback.py` | The last router. Answers anything nobody else handled. |

### `tgbot/services/` — business logic and external services

| File | Responsibility |
|---|---|
| `http.py` | **One** shared `aiohttp.ClientSession` per process with a tuned connection pool and timeouts. All outgoing HTTP goes through it. |
| `quotas.py` | Atomic picture **and message** quotas in Redis: `try_consume*` reserves a slot with INCR, `release*` gives it back on failure, `get_*_usage` feeds the stats screen. Free tier is a lifetime counter without TTL, premium is daily. |
| `limits.py` | Backpressure: a per-user lock in Redis + semaphores for LLM, prompt and image calls. Sheds load instead of building a queue. |
| `migration.py` | Database bootstrap: wait for Postgres, build the engine with an explicit pool, wire the session factory into `AsyncORM`. Migrations are **not** applied here. |
| `runware.py` | Image generation client. A shared SDK behind `asyncio.Lock`, reconnect on drop, retry on a dead websocket. Every request runs Runware's content check; an image that fails it is never delivered. The concurrency ceiling is **not** here — there is one, in `limits.py` (`IMAGE_CONCURRENCY`). |
| `openrouter.py` | The single place where a model call is configured: endpoint, key, attribution headers, model ids and sampling — all from env. |
| `prompt_formation.py` | Calls OpenRouter to build the image prompt. A declined request is never retried: it falls back to a neutral scene built from the profile. |
| `image_prompts.py` | The system prompts themselves: shared content rules + two styles (anime/realistic) × two languages. `tests/unit/test_image_prompts.py` checks structure and rules. |
| `chat.py` | Chat flow: a short transaction to read the context, a short one to write the turn. Returns frozen DTOs, not ORM objects. |
| `profile.py` | Profile CRUD + the active-profile pointer in Redis + premium check. |
| `dialog_history.py` | Chat history in the database: write a turn, read the last 10, trim in one query. |
| `premium.py` | Granting premium by username or id. |
| `style.py` | Read/write `User.style`. |
| `broadcaster.py` | Safe sending with flood-wait handling + mass broadcast. |

### `tgbot/middlewares/` — cross-cutting logic

| File | Responsibility |
|---|---|
| `antiduplicate.py` | Deduplication by `update_id` with `SET NX`. On raw updates. |
| `config.py` | Injects `config` and the shared `redis` into handler data. |
| `database.py` | Get-or-create the user row on **every** update and pass a `user` dict (with premium expiry already applied). Cached in Redis for 60 s; anything that changes cached fields must call `invalidate_user_cache()`. |
| `dev.py` | "Admins only in dev mode". A blocked user gets a reply instead of silence. |

### `tgbot/keyboards/`, `tgbot/misc/`, `tgbot/filters/`

| File | Responsibility |
|---|---|
| `keyboards/inline.py` | Admin, language, agreement and style keyboards. |
| `keyboards/menu.py` | Main menu keyboard. |
| `keyboards/photo_settings.py` | Texts and keyboards of the picture settings. |
| `keyboards/profiles.py` | List / pick / create / delete / edit profiles. |
| `misc/branding.py` | Deployment-specific links and contacts from env (support contact, channel, agreement pages). |
| `misc/localization.py` | String tables and wizard options (ru/en). Handlers still write `if lang == "ru"` inline (~145 places). |
| `misc/start_message_text.py` | Agreement and profile-list texts. |
| `misc/welcome_message.py` | Text shown after a character is created. |
| `misc/language_selected_text.py` | Language confirmation. |
| `misc/states.py` | FSM groups: `BroadcastState` and `ProfileCustomizationState`. |
| `filters/admin.py` | `AdminFilter` based on `ADMINS`. |
| `filters/chat.py` | `IsPrivate`. Applied at the Dispatcher level, so it covers every router. |

---

## Not done yet

| Problem | Where | Why not now |
|---|---|---|
| ~145 inline `if lang == "ru"` instead of tables in `localization.py` | handlers | A large mechanical refactor; the tables exist, an accessor is needed |
| Dead column `users.welcome_sent` | schema | Dropping it is an irreversible migration; the owner decides |
| `delete_old_profile_messages()` (45 days) is never called | `services/dialog_history.py` | A data retention policy, not a bug: the table is already capped at 10 rows per profile |
| No Postgres backups or resource limits in compose | infrastructure | Needs decisions on storage and server size — see `DEPLOY.md` |
| The picture path is not covered by the load test | `tests/load/` | Needs a stub of Runware's websocket protocol |
| `Profile` is the only model without a repository | `services/profile.py` | Two data-access styles coexist |

## What changed in the last pass

Security:

* `/webhook` no longer accepts unauthenticated updates — the bot **refuses to
  start** without `WEBHOOK_SECRET` (it used to log a warning and carry on);
* nginx no longer exposes the local Bot API server and file server to the
  internet;
* `IsPrivate` is finally applied — the filter existed but was not attached to
  any router, so the bot answered every message in any group it was added to;
* `DeveloperMiddleware` is no longer a no-op (both branches were identical),
  and `IN_DEVELOPMENT` is read as a bool, not a string — `"false"` used to be
  truthy.

Bugs:

* `UnboundLocalError` in the profile wizard: a local `import logging` in an
  `except` block broke the logger at the top of the same function;
* editing a profile no longer deletes and re-creates the row — both history
  FKs cascade, so changing an outfit wiped the whole conversation;
* the picture quota is returned on **every** failure path (before: on two of
  four, and a failed prompt silently ate one of the two lifetime pictures);
* message limits (25 lifetime / 200 per day) are actually enforced: the
  premium screen advertised them from the start, but nothing checked them;
* the stats screen counts messages with the same Redis keys the handler spends
  (it used to count history rows, trimmed to 10, so the number could never
  reach the limit);
* the language on the profile-switching screen comes from `user`, not from the
  FSM, which is empty there — English users saw Russian.

Capacity:

* the Postgres pool moved to `DB_POOL_SIZE`/`DB_MAX_OVERFLOW` (30+20 instead
  of a hard-coded 10+10) — exactly what ran out during a registration wave;
* nginx keep-alive is on (it was `keepalive_timeout 0`, i.e. a new TCP
  connection per update) and a keep-alive upstream to the bot was added;
* saving a chat turn takes 3 queries instead of 6;
* the broadcast streams users with keyset pagination instead of loading the
  whole table.

Process:

* **CI finally runs the tests** — 213 of them had been written and never run;
* `F823`/`F841` moved from advisory to blocking: the first one caught a real
  bug;
* checks were added that the webhook secret is enforced and the Bot API is not
  public.

## Target structure

The move happens layer by layer, one flow at a time. Import rule: `routers/`
knows about aiogram; `services/`, `db/`, `clients/` do not.

```
bot/
  __main__.py     process lifecycle
  config.py       the single source of truth for env
  runtime.py      AppContext: every pool and its size on one screen
  webhook.py      aiohttp app, /healthz, /metrics
  db/             models, sessions, repositories (one per aggregate)
  services/       flows; return DTOs, not ORM objects
  clients/        openrouter, runware — timeouts, retries, limits
  routers/        parse the update → call a service → render the reply
  keyboards/      pure functions, no await
  middlewares/    context, user (cached), throttling, dedup
  i18n/           t(key, lang)
```
