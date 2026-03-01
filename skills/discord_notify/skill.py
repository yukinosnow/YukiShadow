"""
Discord Notify Skill – execution handler.

All metadata lives in SKILL.md.
"""

from __future__ import annotations

import logging

from core.base_skill import BaseSkill, SkillResult

logger = logging.getLogger(__name__)


class DiscordNotifySkill(BaseSkill):

    async def execute(self, action: str, params: dict) -> SkillResult:
        if action == "send_message":
            return await self._send_message(params)
        return SkillResult(success=False, error=f"Unknown action '{action}'")

    async def _send_message(self, params: dict) -> SkillResult:
        from core.message_bus import message_bus
        await message_bus.publish("events:discord:send_message", {
            "message": params.get("message", ""),
            "channel_id": params.get("channel_id"),
            "embed": params.get("embed"),
        })
        return SkillResult(success=True, message="Message queued for Discord delivery")
