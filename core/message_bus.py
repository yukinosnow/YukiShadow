"""
YukiShadow - Message Bus

Thin wrapper around Redis providing:
  - Pub/Sub for real-time events between services
  - FIFO queue (Redis List) for reliable task delivery
  - Simple key-value state store

Channel naming conventions:
  events:<service>:<event>   e.g. events:discord:message_received
  queue:<service>            e.g. queue:orchestrator
  state:<key>                e.g. state:jetson:last_position
"""

from __future__ import annotations

import json
import logging
from typing import AsyncIterator

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class MessageBus:

    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None
        self.connected: bool = False   # True only after a successful ping

    async def connect(self) -> None:
        """
        Try to connect to Redis and verify with a PING.
        Logs a warning (does NOT raise) if Redis is unavailable so callers
        can start without Redis and degrade gracefully.
        """
        from core.config import settings
        try:
            r = await aioredis.from_url(settings.redis_url, decode_responses=True)
            await r.ping()
            self._redis = r
            self.connected = True
            logger.info(f"MessageBus connected to Redis ({settings.redis_url})")
        except Exception as exc:
            self.connected = False
            logger.warning(
                f"Redis unavailable ({exc}) — message bus running in offline mode. "
                "Skills that require Redis will fall back to HTTP delivery."
            )

    async def disconnect(self) -> None:
        if self._redis:
            await self._redis.aclose()
            self._redis = None
            self.connected = False

    @property
    def redis(self) -> aioredis.Redis:
        if self._redis is None or not self.connected:
            raise RuntimeError("MessageBus is not connected to Redis.")
        return self._redis

    # ── Pub / Sub ─────────────────────────────────────────────────────────────

    async def publish(self, channel: str, event: dict) -> None:
        await self.redis.publish(channel, json.dumps(event, default=str))

    async def subscribe(self, channel: str) -> AsyncIterator[dict]:
        """Async generator that yields decoded events from a channel."""
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            async for raw in pubsub.listen():
                if raw["type"] == "message":
                    try:
                        yield json.loads(raw["data"])
                    except json.JSONDecodeError as e:
                        logger.warning(f"Bad JSON on channel {channel}: {e}")
        finally:
            await pubsub.unsubscribe(channel)

    # ── Task queue ────────────────────────────────────────────────────────────

    async def enqueue(self, queue: str, task: dict) -> None:
        """Push a task to the tail of a Redis list (FIFO)."""
        await self.redis.rpush(queue, json.dumps(task, default=str))

    async def dequeue(self, queue: str, timeout: int = 5) -> dict | None:
        """Blocking pop from the head of a queue. Returns None on timeout."""
        result = await self.redis.blpop(queue, timeout=timeout)
        if result:
            _, data = result
            return json.loads(data)
        return None

    # ── State store ───────────────────────────────────────────────────────────

    async def set_state(self, key: str, value: dict, ttl: int | None = None) -> None:
        await self.redis.set(f"state:{key}", json.dumps(value, default=str), ex=ttl)

    async def get_state(self, key: str) -> dict | None:
        data = await self.redis.get(f"state:{key}")
        return json.loads(data) if data else None

    async def delete_state(self, key: str) -> None:
        await self.redis.delete(f"state:{key}")


# Singleton
message_bus = MessageBus()
