"""Triage worker: takes runs from the job table and processes them, so a restart never leaves a run stuck.

Start: python -m inbox_helper.worker   (or let the web app run one in-process: EMBEDDED_WORKER=1, the default)

- Starting a run only inserts a run + job row (queued). A worker claims the job, stores each result as soon as it
  arrives, and updates a heartbeat while it works.
- If a worker dies (restart, deploy, crash), its heartbeat goes stale and any worker takes the job over. It
  processes only the messages that have no item yet; cached model outputs cost no AI calls either.
- On Postgres the claim uses FOR UPDATE SKIP LOCKED, so two workers never take the same job. The conditional UPDATE
  after it also makes the claim safe on SQLite, which has no row locks.
- A job that has been taken over max_attempts times is marked failed instead of looping forever; Retry re-queues it.
"""
import os
import signal
import socket
import threading
import time
import uuid
from dataclasses import asdict
from datetime import timedelta
from typing import Callable

from sqlalchemy import and_, func, or_, select, update
from dotenv import load_dotenv
from sqlalchemy.exc import IntegrityError

from .config import CACHE_PATH, DEFAULT_LANES, DEFAULT_POLICY, ROOT, load_api_keys
from .db import BlockedSender, Database, Item, Job, Run, apply_result, utcnow
from .loader import Message
from .pipeline import Cache, Lane, Result, TriageRun, build_lanes

HEARTBEAT_S = 10
STALE_AFTER_S = 60   # a job whose heartbeat is older than this belongs to a dead worker
MAX_ATTEMPTS = 3


def default_lanes() -> list[Lane]:
    return build_lanes(DEFAULT_LANES, load_api_keys(), print)


def blocked_emails(db: Database) -> frozenset[str]:
    with db.Session() as s:
        return frozenset(s.scalars(select(BlockedSender.email)).all())


def enqueue_run(db: Database, messages: list[Message], related: list = (), **run_fields) -> int:
    """Store a run and its job; a worker picks it up. Returns the run id. related: rows with a .run (e.g. the
    imported Gmail messages), stored in the same transaction."""
    with db.write_lock, db.Session() as s:
        run = Run(total=len(messages), status="queued", **run_fields)
        run.job = Job(messages=[asdict(m) for m in messages])
        s.add(run)
        for row in related:
            row.run = run
            s.add(row)
        s.commit()
        return run.id


def merge_lane_stats(previous: list[dict], lanes: list[Lane]) -> list[dict]:
    """Add this attempt's per-lane call counts to those of earlier attempts of the same run."""
    merged = {d["name"]: dict(d) for d in previous or []}
    for lane in lanes:
        d = merged.setdefault(lane.name, {"name": lane.name, "calls": 0, "failures": 0, "disabled": False})
        d["calls"] += lane.calls
        d["failures"] += lane.failures
        d["disabled"] = lane.disabled
    return list(merged.values())


class Worker:
    def __init__(self, db: Database, lanes_factory: Callable[[], list[Lane]] = default_lanes,
                 policy: str | None = None, cache_path=CACHE_PATH, *, name: str | None = None, poll_s: float = 1.0,
                 heartbeat_s: float = HEARTBEAT_S, stale_after_s: float = STALE_AFTER_S,
                 max_attempts: int = MAX_ATTEMPTS, log: Callable[[str], None] = print):
        self.db, self.lanes_factory, self.cache_path = db, lanes_factory, cache_path
        self.policy = policy if policy is not None else DEFAULT_POLICY.read_text(encoding="utf-8")
        self.name = name or f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.poll_s, self.heartbeat_s, self.stale_after_s = poll_s, heartbeat_s, stale_after_s
        self.max_attempts = max_attempts
        self._log = log

    def log(self, msg: str) -> None:
        self._log(f"[worker {self.name}] {msg}")

    # ---- claiming ---------------------------------------------------------------------------------------------
    def claim(self) -> int | None:
        """Take the oldest queued job, or a running one whose worker stopped heartbeating. Returns the job id."""
        stale = utcnow() - timedelta(seconds=self.stale_after_s)
        claimable = or_(Job.status == "queued", and_(Job.status == "running", Job.heartbeat_at < stale))
        with self.db.write_lock, self.db.Session() as s:
            q = select(Job.id, Job.status, Job.worker).where(claimable).order_by(Job.id).limit(1)
            if self.db.is_postgres:
                q = q.with_for_update(skip_locked=True)
            row = s.execute(q).first()
            if row is None:
                return None
            now = utcnow()
            won = s.execute(update(Job).where(Job.id == row.id, claimable).values(
                status="running", worker=self.name, heartbeat_at=now, attempts=Job.attempts + 1,
                started_at=func.coalesce(Job.started_at, now))).rowcount == 1
            s.commit()
        if won and row.status == "running":
            self.log(f"job {row.id}: taking over from {row.worker}, whose heartbeat stopped")
        return row.id if won else None

    def run_once(self) -> bool:
        """Process one job if there is one. Returns whether a job was claimed."""
        job_id = self.claim()
        if job_id is None:
            return False
        self.process(job_id)
        return True

    def run_forever(self, stop: threading.Event) -> None:
        self.log("waiting for jobs")
        while not stop.is_set():
            try:
                worked = self.run_once()
            except Exception as e:  # e.g. the database is briefly unreachable; the job's heartbeat will go stale
                self.log(f"error: {e.__class__.__name__}: {e}")
                worked = False
            if not worked:
                stop.wait(self.poll_s)

    def start_thread(self) -> tuple[threading.Thread, threading.Event]:
        stop = threading.Event()
        thread = threading.Thread(target=self.run_forever, args=(stop,), daemon=True, name=f"worker-{self.name}")
        thread.start()
        return thread, stop

    # ---- processing -------------------------------------------------------------------------------------------
    def process(self, job_id: int) -> None:
        with self.db.Session() as s:
            job = s.get(Job, job_id)
            run_id, attempts = job.run_id, job.attempts
            done = set(s.scalars(select(Item.message_id).where(Item.run_id == run_id)).all())
            messages = [Message(**m) for m in job.messages if m["message_id"] not in done]
        if attempts > self.max_attempts:
            self._finish(job_id, run_id, "failed",
                         f"Stopped {attempts - 1} times before finishing (worker restarts or crashes). "
                         f"{len(messages)} message(s) were not processed; use Retry to continue.", [], 0.0)
            return
        with self.db.write_lock, self.db.Session() as s:
            run = s.get(Run, run_id)
            run.status, run.error = "running", None
            s.commit()
        self.log(f"job {job_id} (run {run_id}, attempt {attempts}): {len(messages)} message(s) to process"
                 + (f", {len(done)} already stored" if done else ""))

        stop = threading.Event()
        beat = threading.Thread(target=self._heartbeat, args=(job_id, stop), daemon=True)
        beat.start()
        started = time.monotonic()
        status, error, lanes = "done", None, []
        try:
            if messages:
                lanes = self.lanes_factory()
                results = TriageRun(lanes, self.policy, cache=Cache(self.cache_path),
                                    on_result=lambda r: self._store([r], run_id), log=self.log,
                                    blocked_senders=blocked_emails(self.db)).run(messages)
                self._store(results, run_id)  # safety net: every message must end up stored
        except Exception as e:  # keep the run visible as failed instead of stuck "running"
            status, error = "failed", f"{e.__class__.__name__}: {e}"
        finally:
            stop.set()
            beat.join()
        self._finish(job_id, run_id, status, error, lanes, time.monotonic() - started)

    def _store(self, results: list[Result], run_id: int) -> None:
        """Insert items for results not stored yet. A worker that took the job over may race us: the unique
        (run_id, message_id) constraint decides, and the loser's copy is dropped."""
        with self.db.write_lock, self.db.Session() as s:
            stored = set(s.scalars(select(Item.message_id).where(Item.run_id == run_id)).all())
            for r in results:
                if r.message_id in stored:
                    continue
                it = Item(run_id=run_id)
                apply_result(it, r)
                s.add(it)
                try:
                    s.commit()
                except IntegrityError:
                    s.rollback()

    def _heartbeat(self, job_id: int, stop: threading.Event) -> None:
        while not stop.wait(self.heartbeat_s):
            try:
                with self.db.write_lock, self.db.Session() as s:
                    owned = s.execute(update(Job).where(Job.id == job_id, Job.worker == self.name)
                                      .values(heartbeat_at=utcnow())).rowcount
                    s.commit()
                if not owned:
                    self.log(f"job {job_id}: another worker took this job over")
                    return
            except Exception as e:  # a missed beat is fine; several in a row hand the job to another worker
                self.log(f"job {job_id}: heartbeat failed: {e}")

    def _finish(self, job_id: int, run_id: int, status: str, error: str | None, lanes: list[Lane],
                elapsed: float) -> None:
        now = utcnow()
        with self.db.write_lock, self.db.Session() as s:
            owned = s.execute(update(Job).where(Job.id == job_id, Job.worker == self.name).values(
                status=status, error=error, finished_at=now, heartbeat_at=now)).rowcount
            if not owned:  # fenced: the job was taken over while we worked; the new owner reports the outcome
                s.rollback()
                self.log(f"job {job_id}: finished, but another worker owns it now; leaving its status alone")
                return
            run = s.get(Run, run_id)
            run.status, run.error, run.finished_at = status, error, now
            run.elapsed_s = round((run.elapsed_s or 0) + elapsed, 1)
            run.lanes = merge_lane_stats(run.lanes, lanes)
            s.commit()
        self.log(f"job {job_id} (run {run_id}): {status}" + (f": {error}" if error else ""))


def main() -> None:
    load_dotenv(ROOT / ".env")  # before Database() reads DATABASE_URL
    db = Database()
    if os.environ.get("AUTO_MIGRATE", "1") != "0":
        db.upgrade()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        # Finish the current job if there is time; if the container is killed first, another worker resumes it.
        signal.signal(sig, lambda *_: stop.set())
    Worker(db).run_forever(stop)


if __name__ == "__main__":
    main()
