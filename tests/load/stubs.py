"""Stub Telegram Bot API and OpenRouter, for load testing.

Hammering the real Telegram API at the target rate gets the bot rate-limited or
banned, and every OpenRouter call costs money, so both are replaced.

The Telegram stub doubles as the measurement point: it records the timestamp of
every sendMessage, which is when the user would actually have seen a reply.

    python -m tests.load.stubs --telegram-port 8099 --openrouter-port 8098
"""

import argparse
import asyncio
import random
import time
from datetime import datetime, timezone

from aiohttp import web

# Latency of the real Bot API, roughly.
TG_MIN_DELAY = 0.02
TG_MAX_DELAY = 0.05

# Lognormal(1.6, 0.6) puts the median near 5s and p99 near 30s, which matches
# what a large chat model actually does.
LLM_MU = 1.6
LLM_SIGMA = 0.6
LLM_MAX = 60.0

# Realistic replies, not lorem ipsum: markdown-hostile characters are the
# point. Escaping bugs only surface on text like this.
REPLIES = [
    "Привет! *отрывается от книги* Как прошёл твой день? 🙂",
    "Ого, интересно… *open_the_map* Давай посмотрим маршрут!",
    "Хочешь попробовать этот рецепт? *наливает чай* Тогда начнём...",
    "Сегодня осилено 3 главы (и даже есть заметки) — 100% правда!",
    "Знаешь, что я люблю? Хорошие вопросы. *улыбается* [#1]",
]

_replies_log: list[dict] = []
_counters = {"sendMessage": 0, "editMessageText": 0, "deleteMessage": 0, "llm_calls": 0}


def _message_json(chat_id: int, text: str) -> dict:
    return {
        "message_id": random.randint(1, 10_000_000),
        "date": int(time.time()),
        "chat": {"id": chat_id, "type": "private"},
        "from": {"id": 1, "is_bot": True, "first_name": "stub"},
        "text": text,
    }


async def telegram_handler(request: web.Request) -> web.Response:
    method = request.match_info["method"]
    # aiogram posts Bot API calls as multipart/form-data, not JSON. Reading
    # only JSON here silently produced empty payloads: every recorded message
    # had chat_id 0 and no text.
    ctype = request.headers.get("Content-Type", "")
    try:
        if ctype.startswith("application/json"):
            payload = await request.json()
        else:
            payload = dict(await request.post())
    except Exception:
        payload = {}

    await asyncio.sleep(random.uniform(TG_MIN_DELAY, TG_MAX_DELAY))
    _counters[method] = _counters.get(method, 0) + 1

    if method == "sendMessage":
        chat_id = int(payload.get("chat_id", 0))
        text = payload.get("text", "")
        _replies_log.append({"chat_id": chat_id, "text": text, "ts": time.time()})
        return web.json_response({"ok": True, "result": _message_json(chat_id, text)})

    if method == "getMe":
        return web.json_response(
            {
                "ok": True,
                "result": {
                    "id": 42,
                    "is_bot": True,
                    "first_name": "stub",
                    "username": "stub_bot",
                },
            }
        )

    if method in ("setWebhook", "deleteMessage", "deleteWebhook"):
        return web.json_response({"ok": True, "result": True})

    if method == "editMessageText":
        chat_id = int(payload.get("chat_id", 0))
        return web.json_response(
            {"ok": True, "result": _message_json(chat_id, payload.get("text", ""))}
        )

    if method == "sendPhoto":
        chat_id = int(payload.get("chat_id", 0))
        return web.json_response({"ok": True, "result": _message_json(chat_id, "photo")})

    return web.json_response({"ok": True, "result": True})


async def stats_handler(_request: web.Request) -> web.Response:
    return web.json_response({"counters": _counters, "replies": _replies_log})


async def reset_handler(_request: web.Request) -> web.Response:
    _replies_log.clear()
    for k in _counters:
        _counters[k] = 0
    return web.json_response({"ok": True})


async def openrouter_handler(_request: web.Request) -> web.Response:
    _counters["llm_calls"] += 1
    # lognormal(1.6, 0.6): median e^1.6 ~= 5.0s, p99 ~= 20s.
    delay = min(random.lognormvariate(LLM_MU, LLM_SIGMA), LLM_MAX)
    await asyncio.sleep(delay)
    return web.json_response(
        {
            "id": "stub",
            "created": int(datetime.now(timezone.utc).timestamp()),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": random.choice(REPLIES)},
                    "finish_reason": "stop",
                }
            ],
        }
    )


def build_telegram_app() -> web.Application:
    app = web.Application(client_max_size=10 * 1024 * 1024)
    app.router.add_post("/bot{token}/{method}", telegram_handler)
    app.router.add_get("/stats", stats_handler)
    app.router.add_post("/reset", reset_handler)
    return app


def build_openrouter_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/chat/completions", openrouter_handler)
    app.router.add_get("/stats", stats_handler)
    return app


async def main(tg_port: int, or_port: int) -> None:
    runners = []
    for app, port, name in (
        (build_telegram_app(), tg_port, "telegram"),
        (build_openrouter_app(), or_port, "openrouter"),
    ):
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", port).start()
        runners.append(runner)
        print(f"stub {name} listening on 127.0.0.1:{port}", flush=True)

    try:
        await asyncio.Event().wait()
    finally:
        for runner in runners:
            await runner.cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--telegram-port", type=int, default=8099)
    parser.add_argument("--openrouter-port", type=int, default=8098)
    args = parser.parse_args()
    asyncio.run(main(args.telegram_port, args.openrouter_port))
