"""HTTP API and static UI host.

The ASGI app instance lives in inbox_helper.server so that importing this module (e.g. in tests) has no side effects.
There is deliberately no endpoint that sends a message: approved replies can only be copied or exported.

Runs are processed by a worker (worker.py) that reads the job table. By default one runs inside this process; pass
embedded_worker=False (EMBEDDED_WORKER=0) when workers run as their own processes.
"""
import csv
import io
import tempfile
from collections import Counter
from datetime import timezone
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Literal

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from .config import (ALL_INTENTS, CACHE_PATH, CODE_FLAGS, DEFAULT_LANES, DEFAULT_POLICY, DEFAULT_PROFILE, FLAGS,
                     PROMPT_VERSION, ROOT, SYSTEM_INTENTS)
from .db import ITEM_FIELDS, BlockedSender, Database, Item, Job, ReviewEvent, Run, apply_result, iso, utcnow
from .loader import InputError, LoadResult, Message, load_messages
from .pipeline import PRIORITY_FLAGS, Cache, Lane, TriageRun
from .worker import Worker, blocked_emails, default_lanes, enqueue_run

SAMPLE_INPUT = ROOT / "data" / "messages.csv"
FRONTEND_DIST = ROOT / "frontend" / "dist"
MAX_UPLOAD_BYTES = 2 * 1024 * 1024


class BlockAction(BaseModel):
    reviewer: str = Field(min_length=1, max_length=80)
    reason: str | None = None


class ReviewAction(BaseModel):
    action: Literal["save", "approve", "reject", "reopen"]
    reviewer: str = Field(min_length=1, max_length=80)
    text: str | None = None   # the reply as edited by the reviewer (save/approve)
    note: str | None = None   # reason for rejecting, optional


def create_app(db: Database | None = None, lanes_factory: Callable[[], list[Lane]] = default_lanes,
               use_cache: bool = True, embedded_worker: bool = True, worker_poll_s: float = 1.0) -> FastAPI:
    """db must already be migrated (Database.upgrade(); server.py does it at startup)."""
    db = db or Database()
    policy = DEFAULT_POLICY.read_text(encoding="utf-8")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if not embedded_worker:
            yield
            return
        thread, stop = Worker(db, lanes_factory, policy, CACHE_PATH if use_cache else None,
                              poll_s=worker_poll_s).start_thread()
        yield
        stop.set()  # an unfinished job keeps its rows; its heartbeat goes stale and the next worker resumes it
        thread.join(timeout=5)

    app = FastAPI(title="Inbox Helper", description="Triage candidate messages; a human reviews every draft.",
                  lifespan=lifespan)

    def session():
        with db.Session() as s:
            yield s

    # ---- serialization ----------------------------------------------------------------------------------------
    def item_json(it: Item, events: bool = False) -> dict:
        d = {f: getattr(it, f) for f in ITEM_FIELDS}
        d.update(id=it.id, run_id=it.run_id, review_status=it.review_status, final_reply=it.final_reply,
                 reviewed_by=it.reviewed_by, reviewed_at=iso(it.reviewed_at), review_note=it.review_note)
        if events:
            d["events"] = [{"action": e.action, "reviewer": e.reviewer, "at": iso(e.at), "before_text": e.before_text,
                            "after_text": e.after_text, "note": e.note} for e in it.events]
        return d

    def run_json(run: Run, items: list[Item]) -> dict:
        return {"id": run.id, "created_at": iso(run.created_at), "finished_at": iso(run.finished_at),
                "input_name": run.input_name, "profile": run.profile, "prompt_version": run.prompt_version,
                "status": run.status, "total": run.total, "processed": len(items), "elapsed_s": run.elapsed_s,
                "error": run.error, "input_errors": run.input_errors, "lanes": run.lanes,
                "by_status": dict(Counter(i.review_status for i in items)),
                "by_intent": dict(Counter(i.intent for i in items)),
                "priority": sum(1 for i in items if i.priority_review and i.review_status == "pending")}

    def get_item(s, item_id: int) -> Item:
        it = s.get(Item, item_id, options=[selectinload(Item.events)])
        if not it:
            raise HTTPException(404, "Item not found")
        return it

    # ---- runs ---------------------------------------------------------------------------------------------------
    def start_run(loaded: LoadResult, input_name: str) -> int:
        if not lanes_factory():  # fail now rather than queue a job no worker can process
            raise HTTPException(503, "No AI provider is configured. Add GEMINI_API_KEY or OPENROUTER_API_KEY to .env.")
        return enqueue_run(db, loaded.messages, input_name=input_name, profile=DEFAULT_PROFILE,
                           prompt_version=PROMPT_VERSION, input_errors=[asdict(e) for e in loaded.errors])

    def load_or_400(path: Path) -> LoadResult:
        try:
            loaded = load_messages(path)
        except InputError as e:
            raise HTTPException(400, str(e))
        if not loaded.messages:
            details = "; ".join(f"row {e.row}: {e.error}" for e in loaded.errors[:5])
            raise HTTPException(400, f"No valid messages to process. {details}")
        return loaded

    # ---- routes -----------------------------------------------------------------------------------------------
    @app.get("/api/health")
    def health():
        """For the host's health check: the database answers. jobs_queued / oldest_queued_s growing means no worker
        is running."""
        try:
            with db.Session() as s:
                queued, oldest = s.execute(select(func.count(Job.id), func.min(Job.created_at))
                                           .where(Job.status == "queued")).one()
        except Exception as e:
            return JSONResponse({"ok": False, "error": f"database: {e.__class__.__name__}"}, status_code=503)
        if oldest is not None and oldest.tzinfo is None:  # SQLite drops tzinfo; stored values are UTC
            oldest = oldest.replace(tzinfo=timezone.utc)
        return {"ok": True, "prompt_version": PROMPT_VERSION, "embedded_worker": embedded_worker,
                "jobs_queued": queued,
                "oldest_queued_s": round((utcnow() - oldest).total_seconds()) if oldest else None}

    @app.get("/api/meta")
    def meta():
        return {"intents": ALL_INTENTS, "system_intents": sorted(SYSTEM_INTENTS), "flags": {**FLAGS, **CODE_FLAGS},
                "priority_flags": sorted(PRIORITY_FLAGS),
                "profile": DEFAULT_PROFILE, "prompt_version": PROMPT_VERSION,
                "lanes": [{"name": c.name, "models": list(c.models)} for c in DEFAULT_LANES]}

    @app.get("/api/runs")
    def list_runs(s=Depends(session)):
        runs = s.scalars(select(Run).order_by(Run.id.desc()).options(selectinload(Run.items))).all()
        return [run_json(r, r.items) for r in runs]

    @app.post("/api/runs/sample", status_code=201)
    def run_sample():
        return {"id": start_run(load_or_400(SAMPLE_INPUT), "Sample inbox (messages.csv)")}

    @app.post("/api/runs", status_code=201)
    async def run_upload(file: UploadFile = File(...)):
        name = Path(file.filename or "upload").name
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "File is larger than 2 MB.")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / name
            path.write_bytes(data)
            loaded = load_or_400(path)
        return {"id": start_run(loaded, name)}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: int, s=Depends(session)):
        run = s.get(Run, run_id, options=[selectinload(Run.items)])
        if not run:
            raise HTTPException(404, "Run not found")
        return run_json(run, run.items)

    @app.post("/api/runs/{run_id}/retry")
    def retry_run(run_id: int, s=Depends(session)):
        """Re-queue a failed run. Messages that already have a draft are kept; only the rest are processed."""
        with db.write_lock:
            run = s.get(Run, run_id, options=[selectinload(Run.job)])
            if not run:
                raise HTTPException(404, "Run not found")
            if run.status != "failed":
                raise HTTPException(409, f"Only failed runs can be retried; this one is {run.status}.")
            if run.job is None:
                raise HTTPException(409, "This run was made before runs could be resumed. Start a new run instead.")
            run.status, run.error, run.finished_at = "queued", None, None
            run.job.status, run.job.error, run.job.attempts, run.job.worker = "queued", None, 0, None
            s.commit()
        return {"id": run_id}

    @app.get("/api/runs/{run_id}/items")
    def list_items(run_id: int, s=Depends(session)):
        items = s.scalars(select(Item).where(Item.run_id == run_id).order_by(Item.id)).all()
        return [item_json(i) for i in items]

    @app.get("/api/items/{item_id}")
    def item_detail(item_id: int, s=Depends(session)):
        return item_json(get_item(s, item_id), events=True)

    @app.post("/api/items/{item_id}/review")
    def review(item_id: int, body: ReviewAction, s=Depends(session)):
        with db.write_lock:
            it = get_item(s, item_id)
            reviewer = body.reviewer.strip()
            current = it.final_reply if it.final_reply is not None else it.draft_reply
            text = (body.text or "").strip()
            if body.action in ("save", "approve", "reject") and it.review_status != "pending":
                raise HTTPException(409, f"This reply is already {it.review_status}. Reopen it first.")
            if body.action == "save":
                if text == current:
                    return item_json(it, events=True)
                s.add(ReviewEvent(item=it, action="edited", reviewer=reviewer, before_text=current, after_text=text))
                it.final_reply = text
            elif body.action == "approve":
                if not text:
                    raise HTTPException(400, "Cannot approve an empty reply.")
                s.add(ReviewEvent(item=it, action="approved", reviewer=reviewer, before_text=it.draft_reply,
                                  after_text=text))
                it.final_reply, it.review_status = text, "approved"
                it.reviewed_by, it.reviewed_at, it.review_note = reviewer, utcnow(), None
            elif body.action == "reject":
                note = (body.note or "").strip() or None
                s.add(ReviewEvent(item=it, action="rejected", reviewer=reviewer, before_text=current, note=note))
                it.review_status, it.reviewed_by, it.reviewed_at, it.review_note = "rejected", reviewer, utcnow(), note
            else:  # reopen
                if it.review_status == "pending":
                    return item_json(it, events=True)
                s.add(ReviewEvent(item=it, action="reopened", reviewer=reviewer, note=it.review_status))
                it.review_status, it.reviewed_by, it.reviewed_at = "pending", None, None
            s.commit()
            s.refresh(it)
            return item_json(it, events=True)

    @app.post("/api/items/{item_id}/regenerate")
    def regenerate(item_id: int, reviewer: str = "reviewer", s=Depends(session)):
        """Ask the model again for one message (no cache). Only for pending items; runs synchronously."""
        it = get_item(s, item_id)
        if it.review_status != "pending":
            raise HTTPException(409, "Only pending items can be regenerated.")
        lanes = lanes_factory()
        if not lanes:
            raise HTTPException(503, "No AI provider is configured.")
        msg = Message(message_id=it.message_id, body=it.body, received_at=it.received_at,
                      candidate_name=it.candidate_name, candidate_email=it.candidate_email, role=it.role,
                      subject=it.subject)
        msg.warnings = [f for f in it.flags if f in ("invalid_email", "duplicate_message")]
        [result] = TriageRun(lanes, policy, cache=Cache(None), batch_size=1, log=print,
                             blocked_senders=blocked_emails(db)).run([msg])
        with db.write_lock:
            before = it.final_reply if it.final_reply is not None else it.draft_reply
            apply_result(it, result)
            it.final_reply = None
            s.add(ReviewEvent(item=it, action="regenerated", reviewer=reviewer.strip() or "reviewer",
                              before_text=before, after_text=result.draft_reply,
                              note=result.error or f"{result.lane} / {result.model}"))
            s.commit()
            s.refresh(it)
        return item_json(it, events=True)

    # ---- blocklist --------------------------------------------------------------------------------------------
    @app.get("/api/blocked")
    def list_blocked(s=Depends(session)):
        rows = s.scalars(select(BlockedSender).order_by(BlockedSender.blocked_at.desc())).all()
        return [{"email": b.email, "reason": b.reason, "blocked_by": b.blocked_by, "blocked_at": iso(b.blocked_at),
                 "source_item_id": b.source_item_id} for b in rows]

    @app.post("/api/items/{item_id}/block")
    def block_sender(item_id: int, body: BlockAction, s=Depends(session)):
        """Block the item's sender and close every pending message from them, in every run."""
        with db.write_lock:
            it = get_item(s, item_id)
            email = it.candidate_email.strip().lower()
            if not email:
                raise HTTPException(400, "This message has no sender email address to block.")
            reviewer, reason = body.reviewer.strip(), (body.reason or "").strip() or None
            if not s.get(BlockedSender, email):
                s.add(BlockedSender(email=email, reason=reason, blocked_by=reviewer, source_item_id=it.id))
            pending = s.scalars(select(Item).where(Item.review_status == "pending")).all()
            for other in [i for i in pending if i.candidate_email.strip().lower() == email]:
                s.add(ReviewEvent(item=other, action="blocked", reviewer=reviewer, note=reason or f"Blocked {email}"))
                other.review_status, other.reviewed_by, other.reviewed_at = "blocked", reviewer, utcnow()
                other.review_note = reason
            s.commit()
            s.refresh(it)
            return item_json(it, events=True)

    @app.delete("/api/blocked/{email}")
    def unblock_sender(email: str, reviewer: str, s=Depends(session)):
        """Future messages from this sender are processed again. Past blocked items stay closed until reopened."""
        with db.write_lock:
            row = s.get(BlockedSender, email.strip().lower())
            if not row:
                raise HTTPException(404, "That sender is not blocked.")
            if row.source_item_id and (src := s.get(Item, row.source_item_id)):
                s.add(ReviewEvent(item=src, action="unblocked", reviewer=reviewer.strip() or "reviewer", note=row.email))
            s.delete(row)
            s.commit()
        return {"unblocked": email}

    @app.get("/api/runs/{run_id}/export.csv")
    def export_approved(run_id: int, s=Depends(session)):
        items = s.scalars(select(Item).where(Item.run_id == run_id, Item.review_status == "approved")
                          .order_by(Item.id)).all()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["message_id", "candidate_name", "candidate_email", "subject", "intent", "final_reply",
                    "reviewed_by", "reviewed_at"])
        for i in items:
            w.writerow([i.message_id, i.candidate_name, i.candidate_email, i.subject, i.intent, i.final_reply,
                        i.reviewed_by, iso(i.reviewed_at)])
        return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="approved_replies_run{run_id}.csv"'})

    @app.get("/api/runs/{run_id}/audit.json")
    def export_audit(run_id: int, s=Depends(session)):
        run = s.get(Run, run_id, options=[selectinload(Run.items).selectinload(Item.events)])
        if not run:
            raise HTTPException(404, "Run not found")
        return {"run": run_json(run, run.items), "items": [item_json(i, events=True) for i in run.items]}

    if FRONTEND_DIST.exists():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="ui")
    return app

