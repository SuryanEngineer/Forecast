"""
WebSocket live price feed, per the roadmap ("WebSockets to push live
price updates to connected clients"). Subscribes to the channel that
order_service.py publishes to (via app/services/price_feed.py) for one
player and forwards every message straight to the browser.

When REDIS_ENABLED is false (independent of DEMO_MODE -- see
app/core/config.py) there's no Redis at all -- app/services/local_pubsub.py
is an in-process substitute with the same channel-per-player shape, so this
route just branches to it instead.
"""
from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.services.price_feed import channel_name

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/prices/{player_id}")
async def price_feed_ws(websocket: WebSocket, player_id: str) -> None:
    await websocket.accept()
    channel = channel_name(player_id)

    if not settings.REDIS_ENABLED:
        from app.services import local_pubsub

        try:
            async for payload in local_pubsub.subscribe(channel):
                await websocket.send_text(payload)
        except WebSocketDisconnect:
            pass
        return

    from redis import asyncio as aioredis

    redis_client = aioredis.from_url(settings.REDIS_URL)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel)
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            data = message["data"]
            await websocket.send_text(data.decode() if isinstance(data, bytes) else data)
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        await redis_client.close()
