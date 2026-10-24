"""Database bootstrap: wait for Postgres, build the engine, wire up AsyncORM.

This module used to also run ``alembic revision --autogenerate`` and
``alembic upgrade head`` on every container start. That is gone:

* autogenerate against live data can silently emit ``DROP COLUMN``;
* two replicas starting at once raced each other;
* the generated revision only survived because ``.:/app`` was bind-mounted,
  so a proper image-based deploy reinvented the schema each time.

Migrations are now an explicit one-shot ``alembic upgrade head`` job (see the
``migrations`` service in docker-compose.yml), and the bot waits for it via
``depends_on: condition: service_completed_successfully``.
"""

import asyncio
import logging
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.ext.asyncio.session import async_sessionmaker

from tgbot.database.orm import AsyncORM

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# After the stage-2 refactor no DB connection is held across a network call, so
# a normal request needs a connection for single-digit milliseconds and a small
# pool goes a long way.
#
# The exception, and the reason these are no longer hard-coded at 10+10, is a
# registration wave: a first-time user is a get-or-create, i.e. an INSERT that
# the user cache cannot absorb by construction. The ramp measured delivery
# falling to 66% at 96 updates/s of all-new users, and the pool was the thing
# that ran out. Day one after a release is exactly that shape.
#
# Watch db_pool_checked_out against db_pool_size in /metrics.
POOL_SIZE = _env_int("DB_POOL_SIZE", 30)
MAX_OVERFLOW = _env_int("DB_MAX_OVERFLOW", 20)
# Fail fast. The 30s default hides pool starvation for half a minute before
# surfacing it as a generic timeout.
POOL_TIMEOUT = 5
POOL_RECYCLE = 1800

# Postgres kills any transaction left idle this long, turning silent pool
# starvation into a loud, greppable error that points at the offending line.
#
# Deliberately loose for now: handlers still hold a transaction across the
# OpenRouter call (user.py:288), so a tight value would break chat outright.
# 150s only catches genuinely stuck transactions — it is above the 120s HTTP
# total timeout in tgbot/services/http.py.
# TODO(stage-2): drop to 15_000 once the chat flow releases its connection
# before the network call. That is what makes this a real invariant check.
IDLE_IN_TRANSACTION_TIMEOUT_MS = 150_000


def build_engine(database_url: str) -> AsyncEngine:
    """Build the async engine with an explicit, tuned pool.

    Previously this was a bare ``create_async_engine(url)``: pool_size=5 plus
    max_overflow=10, and no pre-ping, so any Postgres restart left the pool
    handing out dead connections until the bot was restarted by hand.
    """
    return create_async_engine(
        database_url,
        pool_size=POOL_SIZE,
        max_overflow=MAX_OVERFLOW,
        pool_timeout=POOL_TIMEOUT,
        pool_recycle=POOL_RECYCLE,
        pool_pre_ping=True,
        connect_args={
            "server_settings": {
                "idle_in_transaction_session_timeout": str(IDLE_IN_TRANSACTION_TIMEOUT_MS),
            }
        },
    )


async def wait_for_database(engine: AsyncEngine, timeout: int = 60, interval: int = 1) -> None:
    """Block until Postgres answers, or raise once ``timeout`` elapses."""
    logger.info("Waiting for database (timeout: %ss)", timeout)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    last_error: Exception | None = None

    while loop.time() < deadline:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            logger.info("Database connection established")
            return
        except Exception as e:  # noqa: BLE001 — any driver error means "not ready yet"
            last_error = e
            await asyncio.sleep(interval)

    raise ConnectionError(f"Could not connect to database within {timeout}s: {last_error}")


async def init_database(database_url: str) -> AsyncEngine:
    """Wait for Postgres, wire the session factory into AsyncORM, return the engine.

    The caller owns the returned engine and must ``await engine.dispose()`` on
    shutdown. The old version disposed the engine in a ``finally`` block and
    *then* built the sessionmaker from it.
    """
    engine = build_engine(database_url)
    await wait_for_database(engine)

    async_session_factory = async_sessionmaker(
        engine,
        # Keeps attributes readable after commit. Without this, anything
        # returned from a repository is expired the moment its session closes
        # and raises MissingGreenlet on first attribute access.
        expire_on_commit=False,
    )
    AsyncORM.set_session_factory(async_session_factory)
    AsyncORM.init_models()

    return engine
