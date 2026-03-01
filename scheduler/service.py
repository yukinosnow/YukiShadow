"""
YukiShadow - Scheduler Service

Responsibilities:
  - At startup: load all unfired reminders from DB and schedule them with APScheduler
  - Listen on message bus for new/deleted reminders and update the schedule
  - When a job fires: publish notifications to configured channels via the message bus

APScheduler runs inside an asyncio event loop (AsyncIOScheduler).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import select

from core.message_bus import message_bus
from storage.database import ReminderModel, get_session_factory

logger = logging.getLogger(__name__)


class SchedulerService:

    def __init__(self) -> None:
        from core.config import settings
        self._scheduler = AsyncIOScheduler(timezone=settings.timezone)
        self._listener_task: asyncio.Task | None = None
        self._deleted_task: asyncio.Task | None = None

    async def start(self) -> None:
        await message_bus.connect()
        await self._load_reminders()
        self._listener_task = asyncio.create_task(self._listen_created())
        self._deleted_task = asyncio.create_task(self._listen_deleted())
        self._scheduler.start()
        logger.info("Scheduler service started")

    async def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
        for task in (self._listener_task, self._deleted_task):
            if task:
                task.cancel()
        await message_bus.disconnect()
        logger.info("Scheduler service stopped")

    # ── Bootstrap ─────────────────────────────────────────────────────────────

    async def _load_reminders(self) -> None:
        now = datetime.now(tz=timezone.utc)
        async with get_session_factory()() as session:
            rows = (await session.execute(
                select(ReminderModel).where(ReminderModel.is_fired == False)
            )).scalars().all()

        scheduled = 0
        for r in rows:
            scheduled_at = r.scheduled_at
            if scheduled_at.tzinfo is None:
                scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
            if r.is_recurring or scheduled_at > now:
                self._add_job(r)
                scheduled += 1
            else:
                logger.debug(f"Skipping past reminder {r.id}: {r.title}")
        logger.info(f"Loaded {scheduled}/{len(rows)} reminders from DB")

    # ── Job management ────────────────────────────────────────────────────────

    def _add_job(self, reminder: ReminderModel) -> None:
        job_id = f"reminder_{reminder.id}"
        if reminder.is_recurring and reminder.recurrence_rule:
            trigger = CronTrigger.from_crontab(
                reminder.recurrence_rule,
                timezone=self._scheduler.timezone,
            )
        else:
            trigger = DateTrigger(run_date=reminder.scheduled_at)

        self._scheduler.add_job(
            self._fire,
            trigger=trigger,
            args=[reminder.id, reminder.title, reminder.description, reminder.notification_channels],
            id=job_id,
            replace_existing=True,
            misfire_grace_time=300,
        )
        logger.debug(f"Scheduled job {job_id}: {reminder.title}")

    def _remove_job(self, reminder_id: int) -> None:
        job_id = f"reminder_{reminder_id}"
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)
            logger.debug(f"Removed job {job_id}")

    # ── Fire handler ──────────────────────────────────────────────────────────

    async def _fire(
        self,
        reminder_id: int,
        title: str,
        description: str,
        channels: list[str],
    ) -> None:
        logger.info(f"Firing reminder {reminder_id}: {title}")

        if "discord" in channels:
            await message_bus.publish("events:discord:send_message", {
                "message": None,
                "embed": {
                    "title": f"⏰ Reminder: {title}",
                    "description": description or "Time to act!",
                    "color": 0xFF6B35,
                },
            })

        # Mark non-recurring reminders as fired in the DB
        async with get_session_factory()() as session:
            reminder = await session.get(ReminderModel, reminder_id)
            if reminder and not reminder.is_recurring:
                reminder.is_fired = True
                await session.commit()

        await message_bus.publish("events:reminder:fired", {
            "reminder_id": reminder_id,
            "title": title,
        })

    # ── Event listeners ───────────────────────────────────────────────────────

    async def _listen_created(self) -> None:
        async for event in message_bus.subscribe("events:reminder:created"):
            try:
                async with get_session_factory()() as session:
                    reminder = await session.get(ReminderModel, event["reminder_id"])
                if reminder:
                    self._add_job(reminder)
                    logger.info(f"Dynamically scheduled reminder {reminder.id}")
            except Exception:
                logger.exception("Error handling reminder:created event")

    async def _listen_deleted(self) -> None:
        async for event in message_bus.subscribe("events:reminder:deleted"):
            try:
                self._remove_job(event["reminder_id"])
            except Exception:
                logger.exception("Error handling reminder:deleted event")


async def run_scheduler() -> None:
    service = SchedulerService()
    await service.start()
    try:
        while True:
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        pass
    finally:
        await service.stop()
