"""
Reminder Skill – execution handler.

All metadata (name, description, parameters, LLM context) lives in SKILL.md.
This file only implements execute() and its action handlers.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select

from core.base_skill import BaseSkill, SkillResult
from storage.database import ReminderModel, get_session_factory

logger = logging.getLogger(__name__)


class ReminderSkill(BaseSkill):

    async def execute(self, action: str, params: dict) -> SkillResult:
        dispatch = {
            "create_reminder": self._create,
            "list_reminders": self._list,
            "delete_reminder": self._delete,
        }
        handler = dispatch.get(action)
        if handler is None:
            return SkillResult(success=False, error=f"Unknown action '{action}'")
        try:
            return await handler(params)
        except Exception as exc:
            logger.exception(f"ReminderSkill.{action} failed")
            return SkillResult(success=False, error=str(exc))

    # ── Actions ───────────────────────────────────────────────────────────────

    async def _create(self, params: dict) -> SkillResult:
        try:
            scheduled_at = datetime.fromisoformat(params["scheduled_at"])
        except (KeyError, ValueError) as e:
            return SkillResult(success=False, error=f"Invalid scheduled_at: {e}")

        async with get_session_factory()() as session:
            reminder = ReminderModel(
                title=params["title"],
                description=params.get("description", ""),
                scheduled_at=scheduled_at,
                is_recurring=params.get("is_recurring", False),
                recurrence_rule=params.get("recurrence_rule"),
                notification_channels=params.get("channels", ["discord"]),
            )
            session.add(reminder)
            await session.commit()
            await session.refresh(reminder)

        from core.message_bus import message_bus
        await message_bus.publish("events:reminder:created", {
            "reminder_id": reminder.id,
            "title": reminder.title,
            "scheduled_at": reminder.scheduled_at.isoformat(),
            "is_recurring": reminder.is_recurring,
            "recurrence_rule": reminder.recurrence_rule,
            "channels": reminder.notification_channels,
        })

        return SkillResult(
            success=True,
            data={"reminder_id": reminder.id},
            message=f"Reminder '{reminder.title}' scheduled for {reminder.scheduled_at.strftime('%Y-%m-%d %H:%M')}",
        )

    async def _list(self, params: dict) -> SkillResult:
        limit = int(params.get("limit", 10))
        async with get_session_factory()() as session:
            rows = (await session.execute(
                select(ReminderModel)
                .where(ReminderModel.is_fired == False)
                .order_by(ReminderModel.scheduled_at)
                .limit(limit)
            )).scalars().all()

        return SkillResult(
            success=True,
            data=[
                {
                    "id": r.id,
                    "title": r.title,
                    "description": r.description,
                    "scheduled_at": r.scheduled_at.isoformat(),
                    "is_recurring": r.is_recurring,
                    "recurrence_rule": r.recurrence_rule,
                    "channels": r.notification_channels,
                }
                for r in rows
            ],
        )

    async def _delete(self, params: dict) -> SkillResult:
        reminder_id = int(params["reminder_id"])
        async with get_session_factory()() as session:
            reminder = await session.get(ReminderModel, reminder_id)
            if not reminder:
                return SkillResult(success=False, error=f"Reminder {reminder_id} not found")
            await session.delete(reminder)
            await session.commit()

        from core.message_bus import message_bus
        await message_bus.publish("events:reminder:deleted", {"reminder_id": reminder_id})

        return SkillResult(success=True, message=f"Reminder {reminder_id} deleted")
