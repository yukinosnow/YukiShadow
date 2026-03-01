"""
YukiShadow - Database Layer (SQLite via SQLAlchemy async)

Tables:
  reminders   – scheduled notifications
  tasks       – audit log for skill executions
  watched_files – (stub) files/URLs to monitor  [future]
  conversations – (stub) chat history           [future]

Upgrade path: change DATABASE_URL to postgresql+asyncpg://... to migrate.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import AsyncGenerator

from sqlalchemy import Boolean, DateTime, Integer, JSON, String, Text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


# ── Reminders ─────────────────────────────────────────────────────────────────

class ReminderModel(Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False)
    # cron expression like "0 9 * * 1-5" or None
    recurrence_rule: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # list of channel names: ["discord", "email"]
    notification_channels: Mapped[list] = mapped_column(JSON, default=list)
    extra_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    is_fired: Mapped[bool] = mapped_column(Boolean, default=False)


# ── Task audit log ────────────────────────────────────────────────────────────

class TaskLogModel(Base):
    __tablename__ = "task_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    skill_name: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # pending | running | done | failed
    status: Mapped[str] = mapped_column(String(50), default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ── Stub: watched files / URLs ────────────────────────────────────────────────
# Uncomment when implementing FileManagerSkill.

# class WatchedFileModel(Base):
#     __tablename__ = "watched_files"
#     id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
#     path_or_url: Mapped[str] = mapped_column(String(2000))
#     label: Mapped[str] = mapped_column(String(500), default="")
#     sync_interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
#     last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
#     created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
#     is_active: Mapped[bool] = mapped_column(Boolean, default=True)


# ── Engine + session factory ──────────────────────────────────────────────────

def _build_engine():
    from core.config import settings
    return create_async_engine(settings.database_url, echo=settings.debug)


_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def init_db() -> None:
    """Create all tables. Safe to call multiple times (idempotent)."""
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created/verified")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields a database session."""
    async with get_session_factory()() as session:
        yield session
