"""
Discord Skill – execution handler.

Delivery priority:
  1. Redis pub/sub — primary channel (agent → Redis → Discord bot → channel)
  2. HTTP POST to Discord service (/send) — fallback if Redis is unavailable

Redis is the preferred path because it keeps the agent and Discord bot
loosely coupled. HTTP fallback lets the skill work even when Redis is down
(e.g. during isolated CLI testing with only the Discord service running).
"""

from __future__ import annotations

import logging

import httpx

from core.base_skill import BaseSkill, SkillResult

logger = logging.getLogger(__name__)


class DiscordSkill(BaseSkill):

    async def execute(self, action: str, params: dict) -> SkillResult:
        if action == "send_message":
            return await self._send_message(params)
        return SkillResult(success=False, error=f"Unknown action '{action}'")

    async def _send_message(self, params: dict) -> SkillResult:
        from core.config import settings

        payload = {
            "message": params.get("message", ""),
            "channel_id": params.get("channel_id"),
            "embed": params.get("embed"),
        }

        # ── Primary: Redis pub/sub ────────────────────────────────────────────
        from core.message_bus import message_bus
        if message_bus.connected:
            try:
                await message_bus.publish("events:discord:send_message", payload)
                return SkillResult(success=True, message="Message queued via Redis")
            except Exception as exc:
                logger.warning(f"Redis publish failed ({exc}), trying HTTP fallback")
        else:
            logger.debug("Redis offline, skipping to HTTP fallback")

        # ── Fallback: call Discord service HTTP API ───────────────────────────
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.post(
                    f"{settings.discord_service_url}/send",
                    json=payload,
                )
                resp.raise_for_status()
            return SkillResult(success=True, message="Message sent to Discord (HTTP)")
        except Exception as exc:
            return SkillResult(
                success=False,
                error=(
                    f"Discord service unreachable at {settings.discord_service_url} ({exc}). "
                    "Run: python main.py discord"
                ),
            )
