"""Two things that must not silently regress.

Both were "fixed" once by writing a warning to the log, which is not a control:
the warning scrolled past and the bot ran exposed anyway.
"""

import importlib

import pytest

import bot as bot_module
from tgbot.middlewares.dev import DeveloperMiddleware


# --- webhook authentication ------------------------------------------------

def _webhook_config(monkeypatch, secret: str, allow_insecure: str = ""):
    monkeypatch.setenv("WEBHOOK_SECRET", secret)
    monkeypatch.setenv("ALLOW_INSECURE_WEBHOOK", allow_insecure)
    # WebhookConfig reads os.getenv in its field defaults, evaluated at import.
    importlib.reload(bot_module)
    return bot_module.WebhookConfig()


class _StubBot(bot_module.TgBot):
    """TgBot with just enough wired up to reach setup_webhook's check."""

    def __init__(self, webhook_config):
        self.webhook_config = webhook_config
        self.dp = object()
        self.bot = object()
        self.logger = __import__("logging").getLogger("test")


async def test_bot_refuses_to_start_without_a_webhook_secret(monkeypatch):
    cfg = _webhook_config(monkeypatch, secret="")
    with pytest.raises(RuntimeError, match="WEBHOOK_SECRET"):
        await _StubBot(cfg).setup_webhook()


async def test_the_escape_hatch_is_explicit_and_opt_in(monkeypatch):
    """Local development can bypass the check, but only by asking for it."""
    cfg = _webhook_config(monkeypatch, secret="", allow_insecure="true")
    assert cfg.allow_insecure is True

    cfg = _webhook_config(monkeypatch, secret="", allow_insecure="false")
    assert cfg.allow_insecure is False, "'false' must not read as truthy"


async def test_a_configured_secret_is_carried_into_the_handler(monkeypatch):
    cfg = _webhook_config(monkeypatch, secret="s3cret")
    assert cfg.secret_token == "s3cret"


# --- maintenance gate ------------------------------------------------------

class FakeUser:
    def __init__(self, user_id):
        self.id = user_id


class FakeMessage:
    def __init__(self, user_id):
        self.from_user = FakeUser(user_id)
        self.sent = []

    async def answer(self, text, **_kw):
        self.sent.append(text)


def _config(dev: bool, admins=(1,)):
    misc = type("Misc", (), {"dev": dev})()
    tg = type("TgBot", (), {"admin_ids": list(admins)})()
    return type("Config", (), {"misc": misc, "tg_bot": tg})()


async def _run(dev: bool, user_id: int):
    called = False

    async def handler(_event, _data):
        nonlocal called
        called = True
        return "handled"

    message = FakeMessage(user_id)
    data = {"config": _config(dev), "user": {"language": "en"}}
    await DeveloperMiddleware()(handler, message, data)
    return called, message.sent


async def test_dev_mode_blocks_non_admins():
    """Both branches of this middleware used to call the handler, so it did
    nothing at all and the bot was fully open however IN_DEVELOPMENT was set."""
    called, sent = await _run(dev=True, user_id=999)
    assert called is False
    assert sent, "a blocked user must be told why, not met with silence"


async def test_dev_mode_lets_admins_through():
    called, _ = await _run(dev=True, user_id=1)
    assert called is True


async def test_everyone_passes_when_dev_mode_is_off():
    called, _ = await _run(dev=False, user_id=999)
    assert called is True
