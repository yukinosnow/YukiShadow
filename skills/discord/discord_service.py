"""
Discord Skill – service client for the Discord bot sidecar.

All actions route through the bot's HTTP API (default port 8090).
Redis pub/sub is used as the preferred delivery path for send_message
to keep the agent and bot loosely coupled; the other actions always
use HTTP since they need a synchronous response.

Actions
-------
send_message      – send a plain message or rich embed to a channel
get_messages      – fetch recent non-bot messages from a channel
reply_to_message  – reply to a specific message by ID
"""

from __future__ import annotations

import logging

import httpx

from core.base_skill import BaseSkill, SkillResult

logger = logging.getLogger(__name__)


class DiscordSkill(BaseSkill):

    async def execute(self, action: str, params: dict) -> SkillResult:
        match action:
            case "send_message":
                return await self._send_message(params)
            case "get_messages":
                return await self._get_messages(params)
            case "reply_to_message":
                return await self._reply_to_message(params)
            case _:
                return SkillResult(success=False, error=f"Unknown action '{action}'")

    # ── send_message ──────────────────────────────────────────────────────────

    async def _send_message(self, params: dict) -> SkillResult:
        from core.config import settings

        payload = {
            "message": params.get("message", ""),
            "channel_id": params.get("channel_id"),
            "embed": params.get("embed"),
        }

        # Primary: Redis pub/sub (fire-and-forget, bot picks it up)
        from core.message_bus import message_bus
        if message_bus.connected:
            try:
                await message_bus.publish("events:discord:send_message", payload)
                return SkillResult(success=True, message="Message queued via Redis")
            except Exception as exc:
                logger.warning(f"Redis publish failed ({exc}), trying HTTP fallback")
        else:
            logger.debug("Redis offline, falling back to HTTP")

        # Fallback: direct HTTP to bot sidecar
        return await self._http_post(settings.discord_service_url, "/send", payload)

    # ── get_messages ──────────────────────────────────────────────────────────

    async def _get_messages(self, params: dict) -> SkillResult:
        from core.config import settings

        channel_id = params.get("channel_id")
        limit = params.get("limit", 10)

        query = f"?limit={limit}"
        if channel_id:
            query += f"&channel_id={channel_id}"

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{settings.discord_service_url}/messages{query}"
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            return SkillResult(
                success=False,
                error=f"Discord service unreachable ({exc}). Run: python main.py discord",
            )

        if "error" in data:
            return SkillResult(success=False, error=data["error"])

        messages = data.get("messages", [])
        return SkillResult(
            success=True,
            message=f"Fetched {len(messages)} messages",
            data={"messages": messages},
        )

    # ── reply_to_message ──────────────────────────────────────────────────────

    async def _reply_to_message(self, params: dict) -> SkillResult:
        from core.config import settings

        message_id = params.get("message_id")
        channel_id = params.get("channel_id")
        content = params.get("content", "")

        if not message_id or not channel_id:
            return SkillResult(success=False, error="message_id and channel_id are required")

        payload = {
            "message_id": int(message_id),
            "channel_id": int(channel_id),
            "content": content,
        }
        return await self._http_post(settings.discord_service_url, "/reply", payload)

    # ── helpers ───────────────────────────────────────────────────────────────

    async def _http_post(self, base_url: str, path: str, payload: dict) -> SkillResult:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.post(f"{base_url}{path}", json=payload)
                resp.raise_for_status()
                data = resp.json()
            if not data.get("ok", True):
                return SkillResult(success=False, error=data.get("error", "Unknown error"))
            return SkillResult(success=True, message=f"POST {path} succeeded")
        except Exception as exc:
            return SkillResult(
                success=False,
                error=f"Discord service unreachable at {base_url}{path} ({exc}). Run: python main.py discord",
            )
