"""
Redis pub/sub publisher for live price updates, per the roadmap ("Redis
for order-book state and pub/sub, WebSockets to push live price updates
to connected clients"). order_service.py calls `publish_trade` once per
fill; app/api/v1/ws.py subscribes and forwards to connected browser
clients. This module only publishes -- it never reads back its own
messages, so it has no opinion about who's listening.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from redis import Redis

from app.core.config import settings

_redis: Redis | None = None


def _client() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.REDIS_URL)
    return _redis


def channel_name(player_id: uuid.UUID | str) -> str:
    return f"price:{player_id}"


def publish_trade(player_id: uuid.UUID | str, price: Decimal, quantity: int, executed_at: datetime | None = None) -> None:
    payload = {
        "type": "trade",
        "player_id": str(player_id),
        "price": str(price),
        "quantity": quantity,
        "executed_at": (executed_at or datetime.now(timezone.utc)).isoformat(),
    }

    if not settings.REDIS_ENABLED:
        # No Redis -- fan out via the in-process pub/sub substitute
        # instead. See app/services/local_pubsub.py and config.py's
        # REDIS_ENABLED (independent of DEMO_MODE).
        from app.services import local_pubsub

        local_pubsub.publish(channel_name(player_id), payload)
        return

    try:
        _client().publish(channel_name(player_id), json.dumps(payload))
    except Exception:
        # Never let a Redis hiccup fail an actual trade -- the trade is
        # already durably committed to Postgres by the time this is
        # called; a missed live-price push just means a connected client
        # has to wait for the next trade or a manual refresh.
        pass
