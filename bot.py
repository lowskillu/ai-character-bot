import asyncio
import logging
import signal
import os
from typing import Optional
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass

try:
    import betterlogging as bl
except ImportError:
    bl = None
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from sqlalchemy import text as sa_text
import redis.asyncio as aioredis

from tgbot.config import Config, load_config
from tgbot.filters.chat import IsPrivate
from tgbot.handlers import routers_list
from tgbot.middlewares.config import ConfigMiddleware
from tgbot.middlewares.database import DatabaseMiddleware
from tgbot.middlewares.dev import DeveloperMiddleware
from tgbot.middlewares.antiduplicate import AntiDuplicateMiddleware
from tgbot.services import broadcaster
from tgbot.services.http import close_http_session
from tgbot.services.limits import limits, shed_count
from tgbot.services.migration import init_database


# redis-py leaves max_connections effectively unbounded and opens a new socket
# for every concurrent command. A 160 msg/s load run drove it to 993 open
# connections, against a default Redis maxclients of 10000 and with every
# connection costing memory on both ends. Redis commands here are sub-
# millisecond, so a bounded pool costs nothing and removes the failure mode.
REDIS_POOL_KWARGS = {
    "max_connections": int(os.getenv("REDIS_MAX_CONNECTIONS", "100")),
    "health_check_interval": 30,
    # Deliberately not 2s. A 2s budget left no margin: on a host where the
    # connect took ~2.05s (an IPv6-then-IPv4 fallback) every Redis operation
    # failed, and because the webhook acknowledges before handling, the bot
    # answered 200 to every update and silently dropped all of them. Redis
    # commands themselves are sub-millisecond, so a generous ceiling costs
    # nothing and only catches a genuinely hung connection.
    "socket_connect_timeout": int(os.getenv("REDIS_CONNECT_TIMEOUT", "5")),
    "socket_timeout": int(os.getenv("REDIS_SOCKET_TIMEOUT", "5")),
    "retry_on_timeout": True,
}


@dataclass
class WebhookConfig:
    """Webhook settings."""

    host: str = "0.0.0.0"
    # 80 inside the container; overridable so it can run unprivileged locally.
    port: int = int(os.getenv("WEBHOOK_PORT", "80"))
    path: str = "/webhook"
    # Public webhook URL, from the WEBHOOK_HOST env var
    webhook_url: str = os.getenv("WEBHOOK_HOST", "")
    # Shared secret Telegram echoes back in X-Telegram-Bot-Api-Secret-Token.
    # Without it, anyone who learns the webhook URL can post forged updates
    # claiming to be any user, including an admin.
    secret_token: str = os.getenv("WEBHOOK_SECRET", "")
    # Local development only. Lets the bot start with an unauthenticated
    # webhook; see setup_webhook().
    allow_insecure: bool = os.getenv("ALLOW_INSECURE_WEBHOOK", "").strip().lower() in {
        "1", "true", "yes", "on",
    }
    # Telegram's cap on parallel webhook deliveries. Updates are acknowledged in
    # milliseconds (aiogram handles them in a background task), so this is burst
    # headroom rather than a concurrency limit.
    max_connections: int = 200


class GracefulRequestHandler(SimpleRequestHandler):
    """SimpleRequestHandler that lets in-flight updates finish on shutdown.

    aiogram dispatches each update into a bare asyncio task and its ``close()``
    only shuts the bot session, abandoning them. That dropped every in-progress
    conversation on each deploy.
    """

    SHUTDOWN_TIMEOUT = 30

    async def close(self) -> None:
        pending = getattr(self, "_background_feed_update_tasks", None)
        if pending:
            logging.getLogger(__name__).info(
                "Waiting up to %ss for %s in-flight update(s)",
                self.SHUTDOWN_TIMEOUT, len(pending),
            )
            await asyncio.wait(set(pending), timeout=self.SHUTDOWN_TIMEOUT)
        await super().close()


class TgBot:
    def __init__(self, config: Config, webhook_config: Optional[WebhookConfig] = None):
        self.config = config
        self.webhook_config = webhook_config or WebhookConfig()
        self.use_polling = os.getenv("USE_POLLING", "false").lower() in ("true", "1", "yes")
        self.bot: Optional[Bot] = None
        self.dp: Optional[Dispatcher] = None
        self.redis: Optional[aioredis.Redis] = None
        self.engine = None
        self.app: Optional[web.Application] = None
        self.runner: Optional[web.AppRunner] = None
        self.logger = logging.getLogger(__name__)
        self._setup_logging()

    def _setup_logging(self) -> None:
        """Logging setup"""
        if bl:
            bl.basic_colorized_config(level=logging.INFO)
        else:
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s - %(name)s - %(levelname)s - %(message)s [%(filename)s:%(lineno)d]",
            )
        # INFO rather than DEBUG: debug logging is too heavy under load
        logging.getLogger("aiogram").setLevel(logging.WARNING)
        logging.getLogger("aiohttp").setLevel(logging.WARNING)
        self.logger.info("Initializing bot")

    async def _init_storage(self) -> RedisStorage:
        """Initializing Redis storage"""
        try:
            return RedisStorage.from_url(
                self.config.redis.dsn(), connection_kwargs=REDIS_POOL_KWARGS
            )
        except Exception as e:
            self.logger.error(f"Failed to initialize Redis storage: {e}")
            raise

    async def _init_database(self) -> None:
        """Initializing database"""
        try:
            db_url = (
                f"postgresql+asyncpg://{self.config.postgres.db_user}:{self.config.postgres.db_pass}"
                f"@{self.config.postgres.db_host}:5432/{self.config.postgres.db_name}"
            )
            # Schema migrations are applied by the separate one-shot
            # `migrations` compose service, not here.
            self.engine = await init_database(db_url)
        except Exception as e:
            self.logger.error(f"Database initialization failed: {e}")
            raise

    async def setup_bot(self) -> None:
        """Bot setup"""
        try:
            storage = await self._init_storage()
            # Configurable so load tests can point at a stub Bot API server
            # instead of hammering the real one.
            api_base = os.getenv("TELEGRAM_API_BASE", "http://telegram-api-server:8081")
            session = AiohttpSession(api=TelegramAPIServer.from_base(api_base))
            # aiogram builds its connector from this dict and never exposes it;
            # aiohttp's default limit of 100 would cap concurrent Bot API calls,
            # and each chat turn makes three of them (typing, delete, reply).
            session._connector_init.update(
                limit=int(os.getenv("TELEGRAM_CONNECTOR_LIMIT", "500")),
                limit_per_host=int(os.getenv("TELEGRAM_CONNECTOR_LIMIT", "500")),
            )

            self.bot = Bot(
                token=self.config.tg_bot.token, parse_mode="HTML", session=session
            )
            self.dp = Dispatcher(storage=storage)

            # Shared Redis client (anti-duplicate middleware, locks, quotas)
            self.redis = aioredis.from_url(self.config.redis.dsn(), **REDIS_POOL_KWARGS)

            # Register handlers and middlewares
            self.dp.include_routers(*routers_list)
            self._register_filters()
            self._register_middlewares()

        except Exception as e:
            self.logger.error(f"Bot setup failed: {e}")
            raise

    def _register_filters(self) -> None:
        """Private chats only, enforced once for every router.

        A router-level filter on the Dispatcher gates its own handlers *and*
        every nested router, so this is the single place that has to be right.
        Without it, adding the bot to a group made fallback_router — which
        matches every message — answer everything said there, and every free-text
        message in that group became a paid LLM call.
        """
        if not self.dp:
            raise RuntimeError("Dispatcher not initialized")

        self.dp.message.filter(IsPrivate())
        self.dp.callback_query.filter(IsPrivate())

    def _register_middlewares(self) -> None:
        """Register middlewares"""
        if not self.dp:
            raise RuntimeError("Dispatcher not initialized")
            
        # AntiDuplicateMiddleware runs on raw updates only
        if self.redis:
            self.dp.update.outer_middleware(AntiDuplicateMiddleware(self.redis))
        
        middleware_types = [
            ConfigMiddleware(self.config, self.redis),
            DatabaseMiddleware(),
            DeveloperMiddleware(),
        ]

        for middleware in middleware_types:
            self.dp.message.outer_middleware(middleware)
            self.dp.callback_query.outer_middleware(middleware)

    async def setup_webhook(self) -> None:
        """Webhook setup with validation"""
        if not self.dp or not self.bot:
            raise RuntimeError(
                "Bot and dispatcher must be initialized before webhook setup"
            )

        # Refuse to start rather than warn. An unauthenticated webhook lets
        # anyone who learns the URL post updates claiming to be any user id —
        # including an admin, which reaches /admin's broadcast-to-everyone and
        # /addpremium. A warning in the log is not a control; it scrolled past
        # unnoticed and the bot ran exposed.
        if not self.webhook_config.secret_token:
            if not self.webhook_config.allow_insecure:
                raise RuntimeError(
                    "WEBHOOK_SECRET is not set. The webhook would accept forged "
                    "updates from anyone who learns its URL. Generate one with:\n"
                    '  python -c "import secrets; print(secrets.token_urlsafe(48))"\n'
                    "and put it in .env. For local development only, set "
                    "ALLOW_INSECURE_WEBHOOK=true to bypass this check."
                )
            self.logger.warning(
                "ALLOW_INSECURE_WEBHOOK is set — the webhook accepts "
                "unauthenticated updates. Never do this in production."
            )

        self.app = web.Application()
        self.app.router.add_get("/healthz", self._healthz)
        self.app.router.add_get("/metrics", self._metrics)
        webhook_handler = GracefulRequestHandler(
            dispatcher=self.dp,
            bot=self.bot,
            secret_token=self.webhook_config.secret_token or None,
        )
        webhook_handler.register(self.app, path=self.webhook_config.path)
        setup_application(self.app, self.dp, bot=self.bot)

    async def _healthz(self, _request: web.Request) -> web.Response:
        """Liveness plus a real dependency check.

        Returns 503 when Postgres or Redis is unreachable, so an orchestrator
        can restart or drain the container instead of routing traffic to a bot
        that cannot answer anyone.
        """
        checks = {}
        try:
            async with self.engine.connect() as conn:
                await conn.execute(sa_text("SELECT 1"))
            checks["postgres"] = "ok"
        except Exception as e:  # noqa: BLE001
            checks["postgres"] = f"error: {type(e).__name__}"
        try:
            await self.redis.ping()
            checks["redis"] = "ok"
        except Exception as e:  # noqa: BLE001
            checks["redis"] = f"error: {type(e).__name__}"

        healthy = all(v == "ok" for v in checks.values())
        return web.json_response(checks, status=200 if healthy else 503)

    async def _metrics(self, _request: web.Request) -> web.Response:
        """The few numbers worth alerting on.

        db_pool_checked_out approaching pool_size, or a rising shed count, are
        the two signals that say the bot is past its capacity.
        """
        pool = self.engine.pool if self.engine else None
        return web.json_response(
            {
                "db_pool_size": pool.size() if pool else None,
                "db_pool_checked_out": pool.checkedout() if pool else None,
                "db_pool_overflow": pool.overflow() if pool else None,
                "requests_shed_total": shed_count(),
                "llm_slots_free": limits.llm._value,
                "image_slots_free": limits.image._value,
            }
        )

    @asynccontextmanager
    async def bot_context(self):
        """Context manager for starting and shutting down the bot"""
        try:
            await self._init_database()
            await self.setup_bot()
            if not self.use_polling:
                await self.setup_webhook()

            # set_webhook replaces the previous registration atomically. The old
            # delete_webhook() first left a window with no webhook at all.
            if self.use_polling:
                if self.bot:
                    await self.bot.delete_webhook(drop_pending_updates=True)
                    self.logger.info("Deleted webhook for polling mode")
            elif self.bot and self.dp:
                await self.bot.set_webhook(
                    self.webhook_config.webhook_url,
                    secret_token=self.webhook_config.secret_token or None,
                    max_connections=self.webhook_config.max_connections,
                    allowed_updates=self.dp.resolve_used_update_types(),
                )

            # Notify admins
            admin_users = self.config.tg_bot.admin_ids
            if self.bot:
                await broadcaster.broadcast(
                    self.bot, admin_users, "Bot started successfully"
                )

            yield

        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Release every long-lived resource, in dependency order."""
        try:
            # Stop accepting new updates first, then drain what is in flight.
            # runner.cleanup() invokes the aiohttp shutdown signals, which is
            # what gives GracefulRequestHandler.close() a chance to run.
            if self.runner:
                await self.runner.cleanup()

            admin_users = self.config.tg_bot.admin_ids
            if self.bot:
                await broadcaster.broadcast(
                    self.bot, admin_users, "Bot is shutting down..."
                )

            if self.bot:
                await self.bot.session.close()
            await close_http_session()
            if self.redis:
                await self.redis.close()
            if self.engine:
                await self.engine.dispose()

            self.logger.info("Shutdown completed successfully")

        except Exception as e:
            self.logger.error(f"Error during shutdown: {e}")
        # No asyncio.get_event_loop().stop() here. asyncio.run() owns this loop
        # and stopping it mid-shutdown killed the remaining cleanup, which is
        # why in-flight conversations died on every deploy.

    def _install_signal_handlers(self, stop_event: asyncio.Event) -> None:
        """Ask the run loop to exit on SIGTERM/SIGINT.

        The handler only sets an event; the actual teardown happens on the main
        path so it cannot race with the rest of shutdown.
        """
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:
                # Windows does not support add_signal_handler; dev only.
                self.logger.debug("Signal handler for %s unavailable", sig)

    async def start(self) -> None:
        """Bot start"""
        async with self.bot_context():
            try:
                stop_event = asyncio.Event()
                self._install_signal_handlers(stop_event)

                if self.use_polling:
                    self.logger.info("Bot running in POLLING mode")
                    polling_task = asyncio.create_task(
                        self.dp.start_polling(self.bot, allowed_updates=self.dp.resolve_used_update_types())
                    )
                    await stop_event.wait()
                    await self.dp.stop_polling()
                    polling_task.cancel()
                    with suppress(Exception):
                        await polling_task
                else:
                    # Start web-server
                    if not self.app:
                        raise RuntimeError("Web application not initialized")
                    self.runner = web.AppRunner(self.app)
                    await self.runner.setup()
                    site = web.TCPSite(
                        self.runner,
                        host=self.webhook_config.host,
                        port=self.webhook_config.port,
                    )
                    await site.start()

                    self.logger.info(
                        f"Bot started and listening on {self.webhook_config.host}:"
                        f"{self.webhook_config.port}"
                    )
                    await stop_event.wait()
                    self.logger.info("Stop requested, shutting down")

            except Exception as e:
                self.logger.error(f"Critical error during bot execution: {e}")
                raise


def main():
    try:
        config = load_config(".env")
        bot = TgBot(config)
        asyncio.run(bot.start())
    except Exception as e:
        logging.error(f"Failed to start bot: {e}")
        raise
    finally:
        logging.info("Bot stopped")


if __name__ == "__main__":
    main()
