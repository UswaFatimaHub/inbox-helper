"""Persistence for runs, triaged items, and the review audit trail.

SQLite by default (.data/inbox.db). Set DATABASE_URL (e.g. postgresql+psycopg://user:pass@host/db) to use Postgres;
the schema is plain SQLAlchemy and does not depend on SQLite features.
"""
import os
import threading
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
                        create_engine)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import ROOT


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:  # SQLite drops tzinfo; everything is stored in UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat(timespec="seconds")


class Base(DeclarativeBase):
    pass


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_name: Mapped[str] = mapped_column(String(255))
    profile: Mapped[str] = mapped_column(String(32))
    prompt_version: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="running")  # running | done | failed
    total: Mapped[int] = mapped_column(Integer, default=0)
    elapsed_s: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)
    input_errors: Mapped[list] = mapped_column(JSON, default=list)
    lanes: Mapped[list] = mapped_column(JSON, default=list)

    items: Mapped[list["Item"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class Item(Base):
    """One candidate message, the AI's triage of it, and its review state."""
    __tablename__ = "items"
    __table_args__ = (UniqueConstraint("run_id", "message_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    # original message
    message_id: Mapped[str] = mapped_column(String(128))
    received_at: Mapped[str] = mapped_column(String(64), default="")
    candidate_name: Mapped[str] = mapped_column(String(255), default="")
    candidate_email: Mapped[str] = mapped_column(String(255), default="")
    role: Mapped[str] = mapped_column(String(255), default="")
    subject: Mapped[str] = mapped_column(String(500), default="")
    body: Mapped[str] = mapped_column(Text)
    # AI triage
    intent: Mapped[str] = mapped_column(String(40), index=True)
    secondary_intent: Mapped[str | None] = mapped_column(String(40))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    flags: Mapped[list] = mapped_column(JSON, default=list)
    priority_review: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(Text, default="")
    draft_reply: Mapped[str] = mapped_column(Text, default="")
    lane: Mapped[str] = mapped_column(String(64), default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    prompt_version: Mapped[str] = mapped_column(String(16), default="")
    latency_s: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)
    processed_at: Mapped[str] = mapped_column(String(64), default="")
    # human review
    review_status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending|approved|rejected|blocked
    final_reply: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(String(80))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)

    run: Mapped[Run] = relationship(back_populates="items")
    events: Mapped[list["ReviewEvent"]] = relationship(back_populates="item", cascade="all, delete-orphan",
                                                       order_by="ReviewEvent.id")


class ReviewEvent(Base):
    """Append-only audit trail: every review action with the text before and after."""
    __tablename__ = "review_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    action: Mapped[str] = mapped_column(String(16))  # edited|approved|rejected|reopened|regenerated|blocked|unblocked
    reviewer: Mapped[str] = mapped_column(String(80))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    before_text: Mapped[str | None] = mapped_column(Text)
    after_text: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)

    item: Mapped[Item] = relationship(back_populates="events")


class BlockedSender(Base):
    """Senders whose messages are never sent to the AI or answered. Added only by a reviewer's explicit action."""
    __tablename__ = "blocked_senders"

    email: Mapped[str] = mapped_column(String(255), primary_key=True)  # stored lower-cased
    reason: Mapped[str | None] = mapped_column(Text)
    blocked_by: Mapped[str] = mapped_column(String(80))
    blocked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source_item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id"))


class Database:
    def __init__(self, url: str | None = None):
        url = url or os.environ.get("DATABASE_URL") or f"sqlite:///{(ROOT / '.data' / 'inbox.db').as_posix()}"
        kwargs: dict = {}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            if url in ("sqlite://", "sqlite:///:memory:"):
                kwargs["poolclass"] = StaticPool  # one shared in-memory DB (tests)
            else:
                (ROOT / ".data").mkdir(exist_ok=True)
        self.engine = create_engine(url, **kwargs)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)
        self.write_lock = threading.Lock()  # SQLite allows one writer; harmless on Postgres
        Base.metadata.create_all(self.engine)
