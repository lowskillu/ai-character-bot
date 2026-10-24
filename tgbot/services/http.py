"""One shared aiohttp session for all outbound HTTP.

Both OpenRouter call sites used to do ``async with aiohttp.ClientSession()``
per request, which meant a fresh TCP connection and TLS handshake on every
single user message and threw away connection reuse entirely.

The session is created lazily on first use and must be closed on shutdown via
:func:`close_http_session`.
"""

import asyncio
import logging
import os
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# This is a throughput ceiling, not just a resource cap: sustained throughput is
# bounded by limit / request_latency. With a 5s median LLM call, a limit of 200
# caps the chat path at ~40 requests/s no matter how much CPU is spare. Raise it
# together with LLM_CONCURRENCY in tgbot/services/limits.py — the smaller of the
# two wins.
CONNECTOR_LIMIT = _env_int("HTTP_CONNECTOR_LIMIT", 1000)
CONNECTOR_LIMIT_PER_HOST = _env_int("HTTP_CONNECTOR_LIMIT_PER_HOST", 1000)
DNS_CACHE_TTL = 300
KEEPALIVE_TIMEOUT = 60

# Was 300s on the chat path. A chat bot that answers after five minutes
# has already lost the user; fail earlier and let the caller shed load.
TOTAL_TIMEOUT = 120
CONNECT_TIMEOUT = 10
SOCK_READ_TIMEOUT = 60

_session: Optional[aiohttp.ClientSession] = None
_lock = asyncio.Lock()


async def get_http_session() -> aiohttp.ClientSession:
    """Return the process-wide session, creating it on first call."""
    global _session

    if _session is not None and not _session.closed:
        return _session

    async with _lock:
        # Re-check: another task may have created it while we waited.
        if _session is not None and not _session.closed:
            return _session

        connector = aiohttp.TCPConnector(
            limit=CONNECTOR_LIMIT,
            limit_per_host=CONNECTOR_LIMIT_PER_HOST,
            ttl_dns_cache=DNS_CACHE_TTL,
            keepalive_timeout=KEEPALIVE_TIMEOUT,
        )
        timeout = aiohttp.ClientTimeout(
            total=TOTAL_TIMEOUT,
            connect=CONNECT_TIMEOUT,
            sock_read=SOCK_READ_TIMEOUT,
        )
        _session = aiohttp.ClientSession(connector=connector, timeout=timeout)
        logger.info("Created shared HTTP session (limit=%s)", CONNECTOR_LIMIT)
        return _session


async def close_http_session() -> None:
    """Close the shared session. Safe to call when it was never created."""
    global _session

    if _session is not None and not _session.closed:
        await _session.close()
        logger.info("Closed shared HTTP session")
    _session = None
