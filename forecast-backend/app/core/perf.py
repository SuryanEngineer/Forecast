"""
Request timing, so "it is slow" turns into "THIS endpoint is slow".

A plain ASGI middleware (no per-request thread, no body buffering): it times every HTTP request, keeps per-path counters and
the slowest recent requests, and logs anything over SLOW_SECONDS. `snapshot()` is shown under `perf` in /health.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import deque

logger = logging.getLogger("forecast.perf")

SLOW_SECONDS = 2.0
_lock = threading.Lock()
_paths: dict[str, list] = {}  # path -> [count, total_s, max_s]
_slow: deque = deque(maxlen=25)
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def _norm(path: str) -> str:
    return _UUID.sub("{id}", path)[:120]


def record(method: str, path: str, status: int, seconds: float) -> None:
    key = f"{method} {_norm(path)}"
    with _lock:
        row = _paths.get(key)
        if row is None:
            if len(_paths) >= 300:
                return
            row = _paths[key] = [0, 0.0, 0.0]
        row[0] += 1
        row[1] += seconds
        row[2] = max(row[2], seconds)
        if seconds >= SLOW_SECONDS:
            _slow.append({"at": int(time.time()), "path": key, "status": status, "s": round(seconds, 2)})
    if seconds >= SLOW_SECONDS:
        logger.warning("SLOW %s -> %s in %.2fs", key, status, seconds)


def snapshot() -> dict:
    with _lock:
        top = sorted(_paths.items(), key=lambda kv: kv[1][1], reverse=True)[:12]  # by total time spent
        return {
            "by_total_time": [{"path": k, "n": v[0], "avg_s": round(v[1] / v[0], 3), "max_s": round(v[2], 2)} for k, v in top],
            "slow_recent": list(_slow),
        }


class PerfMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        status = {"code": 0}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = scope.get("path", "")
            if path != "/health":
                record(scope.get("method", "GET"), path, status["code"], time.perf_counter() - start)
