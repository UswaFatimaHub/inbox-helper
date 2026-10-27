"""Persistence for runs, triage jobs, triaged items, and the review audit trail.

SQLite by default (.data/inbox.db). Set DATABASE_URL (e.g. postgresql+psycopg://user:pass@host/db) to use Postgres;
the schema is plain SQLAlchemy and does not depend on SQLite features.

The schema is owned by Alembic (inbox_helper/migrations). Database() only connects; call upgrade() (or run
"alembic upgrade head") to create or update the tables. Every schema change needs a new migration.
"""
import os
import threading
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
                        create_engine, inspect, text)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import ROOT

MIGRATIONS_DIR = ROOT / "inbox_helper" / "migrations"
BASELINE_REVISION = "0001"  # the schema create_all() made before Alembic was added
MIGRATION_LOCK_ID = 4_810_117_221  # any constant; Postgres advisory lock held while migrating


def lock_for_migration(conn) -> None:
    """Serialise migrations across processes (web + worker start together). Released when the transaction ends."""
    if conn.dialect.name == "postgresql":
        conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": MIGRATION_LOCK_ID})


def database_url(url: str | None = None) -> str:
    """DATABASE_URL, or the local SQLite file. Hosts hand out postgres:// URLs; SQLAlchemy needs the driver named."""
    url = url or os.environ.get("DATABASE_URL") or f"sqlite:///{(ROOT / '.data' / 'inbox.db').as_posix()}"
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


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
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued | running | done | failed
    total: Mapped[int] = mapped_column(Integer, default=0)
    elapsed_s: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)
    input_errors: Mapped[list] = mapped_column(JSON, default=list)
    lanes: Mapped[list] = mapped_column(JSON, default=list)

    items: Mapped[list["Item"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    job: Mapped["Job | None"] = relationship(back_populates="run", cascade="all, delete-orphan")


class Job(Base):
    """The work behind a run, kept in the database so it survives restarts (see worker.py).

    A worker claims a queued job, or a running one whose heartbeat has gone stale because its worker died, and
    processes only the messages that have no item yet. 'worker' fences the claim: a worker that lost its job to a
    stale-heartbeat takeover cannot overwrite the new owner's status.
    """
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)  # queued|running|done|failed
    messages: Mapped[list] = mapped_column(JSON)  # the validated input, so a resumed job does not need the upload
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    worker: Mapped[str | None] = mapped_column(String(128))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)

    run: Mapped[Run] = relationship(back_populates="job")


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
    action: Mapped[str] = mapped_column(String(16))  # edited|approved|rejected|reopened|regenerated|blocked|unblocked|quarantined
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


ITEM_FIELDS = ("message_id", "received_at", "candidate_name", "candidate_email", "role", "subject", "body", "intent",
               "secondary_intent", "confidence", "flags", "priority_review", "reason", "draft_reply", "lane", "model",
               "prompt_version", "latency_s", "error", "processed_at")


def apply_result(it: Item, r) -> None:
    """Copy a pipeline Result onto an Item."""
    for f in ITEM_FIELDS:
        setattr(it, f, getattr(r, f))
    it.review_status = r.review_status


class Database:
    def __init__(self, url: str | None = None):
        url = database_url(url)
        kwargs: dict = {}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            if url in ("sqlite://", "sqlite:///:memory:"):
                kwargs["poolclass"] = StaticPool  # one shared in-memory DB (tests)
            else:
                (ROOT / ".data").mkdir(exist_ok=True)
        else:
            kwargs["pool_pre_ping"] = True  # hosted Postgres drops idle connections
        self.url = url
        self.engine = create_engine(url, **kwargs)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)
        self.write_lock = threading.Lock()  # SQLite allows one writer; harmless on Postgres

    @property
    def is_postgres(self) -> bool:
        return self.engine.dialect.name == "postgresql"

    def upgrade(self, revision: str = "head") -> None:
        """Apply pending migrations. Safe to call from several processes at once on Postgres (advisory lock).

        A database made by create_all() before Alembic existed is stamped as the baseline first, so its data is kept.
        """
        from alembic import command

        with self.engine.begin() as conn:
            lock_for_migration(conn)
            tables = set(inspect(conn).get_table_names())
            cfg = self._alembic_config(conn)
            if "runs" in tables and "alembic_version" not in tables:
                command.stamp(cfg, BASELINE_REVISION)
            command.upgrade(cfg, revision)

    def downgrade(self, revision: str) -> None:
        from alembic import command

        with self.engine.begin() as conn:
            lock_for_migration(conn)
            command.downgrade(self._alembic_config(conn), revision)

    @staticmethod
    def _alembic_config(conn):
        from alembic.config import Config

        cfg = Config()
        cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
        cfg.attributes["connection"] = conn
        return cfg
