"""
In-process pub/sub substitute for demo mode (see app/core/config.py's
DEMO_MODE and DEMO_MODE.md). The real app uses Redis pub/sub
(app/services/price_feed.py + app/api/v1/ws.py) so the live price feed
works across multiple server processes; demo mode is deliberately a
single process with zero external services, so a plain in-memory
broadcaster is all it needs -- same channel-per-player shape, so
price_feed.py and ws.py only need a small branch each, not a rewrite.

The tricky part: `publish()` can be called from a worker thread (FastAPI
runs sync `def` endpoints in a threadpool, and the bot/demo-tournament
background loops call into service code via `asyncio.to_thread`), but
the subscribers are `asyncio.Queue`s that belong to the main event loop.
Touching an asyncio.Queue from the wrong thread is unsafe, so `publish()`
hands delivery off to the loop via `call_soon_threadsafe` instead of
calling `queue.put_nowait` directly.
"""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any, AsyncIterator

_subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
_loop: asyncio.AbstractEventLoop | None = None


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Call once, from app.main's lifespan startup (demo mode only), so
    publish() has a loop to schedule delivery onto no matter what thread
    it's called from."""
    global _loop
    _loop = loop


def publish(channel: str, message: dict[str, Any]) -> None:
    if _loop is None:
        # Demo mode used outside the normal app lifespan (e.g. a one-off
        # script) -- nobody is listening yet, so there's nothing to do.
        return

    payload = json.dumps(message)

    def _deliver() -> None:
        for queue in list(_subscribers.get(channel, ())):
            queue.put_nowait(payload)

    _loop.call_soon_threadsafe(_deliver)


async def subscribe(channel: str) -> AsyncIterator[str]:
    """Async generator yielding raw JSON strings, one per publish() call
    on this channel -- mirrors the shape app/api/v1/ws.py already expects
    from the real Redis subscriber, so the route can stay almost
    identical between modes."""
    queue: asyncio.Queue = asyncio.Queue()
    _subscribers[channel].add(queue)
    try:
        while True:
            yield await queue.get()
    finally:
        _subscribers[channel].discard(queue)
