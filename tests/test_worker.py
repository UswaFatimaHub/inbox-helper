"""Job table + worker: runs survive restarts, resume only unfinished messages, and are never taken by two workers."""
import json
import re
import threading
import time
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select, update

from inbox_helper.api import create_app
from inbox_helper.db import Database, Item, Job, Run, utcnow
from inbox_helper.loader import Message
from inbox_helper.pipeline import Lane, TriageRun
from inbox_helper.providers import Completion, RateLimiter
from inbox_helper.worker import Worker, enqueue_run


class CountingClient:
    """Like the API tests' fake model, but remembers which messages it was asked about."""

    def __init__(self):
        self.seen: list[str] = []

    def complete(self, system, user):
        ids = re.findall(r'"message_id": "([^"]+)"', user)
        self.seen += ids
        return Completion(json.dumps({"results": [
            {"message_id": i, "intent": "application_status", "confidence": 0.9, "flags": [], "reason": "test",
             "draft_reply": "Thanks for your message. The recruiter will follow up.\n\nBrightpath Recruiting Team"}
            for i in ids]}), "fake", 0.0)


def messages(n=5):
    return [Message(message_id=f"T{i}", body=f"Any update on my application? ({i})") for i in range(1, n + 1)]


def make_worker(db, client=None, name="w1", **kw):
    client = client or CountingClient()
    return Worker(db, lambda: [Lane("fake", client, RateLimiter(100_000), 1)], policy="Policy.", cache_path=None,
                  name=name, log=lambda _: None, **kw), client


def enqueue(db, n=5):
    return enqueue_run(db, messages(n), input_name="test", profile="standard", prompt_version="v3")


def job_of(db, run_id) -> Job:
    with db.Session() as s:
        return s.scalars(select(Job).where(Job.run_id == run_id)).one()


def run_of(db, run_id) -> Run:
    with db.Session() as s:
        return s.get(Run, run_id)


def stored_ids(db, run_id) -> list[str]:
    with db.Session() as s:
        return sorted(s.scalars(select(Item.message_id).where(Item.run_id == run_id)).all())


def go_stale(db, run_id, seconds=600):
    with db.Session() as s:
        s.execute(update(Job).where(Job.run_id == run_id).values(heartbeat_at=utcnow() - timedelta(seconds=seconds)))
        s.commit()


def test_queued_job_is_processed_and_run_marked_done(db):
    run_id = enqueue(db)
    assert run_of(db, run_id).status == "queued"
    worker, client = make_worker(db)
    assert worker.run_once()
    assert not worker.run_once()  # nothing left
    run, job = run_of(db, run_id), job_of(db, run_id)
    assert run.status == job.status == "done" and job.attempts == 1 and job.worker == "w1"
    assert stored_ids(db, run_id) == [f"T{i}" for i in range(1, 6)] and sorted(client.seen) == stored_ids(db, run_id)
    assert run.lanes == [{"name": "fake", "calls": 1, "failures": 0, "disabled": False}]


def test_job_of_a_dead_worker_is_resumed_without_redoing_stored_messages(db):
    run_id = enqueue(db)
    dead, _ = make_worker(db, name="dead")
    assert dead.claim() == job_of(db, run_id).id
    # the dead worker stored two results before it crashed
    fake = Lane("fake", CountingClient(), RateLimiter(100_000), 1)
    dead._store(TriageRun([fake], "Policy.", log=lambda _: None).run(messages()[:2]), run_id)
    go_stale(db, run_id)

    worker, client = make_worker(db, name="w2")
    assert worker.run_once()
    assert sorted(client.seen) == ["T3", "T4", "T5"]  # only the unfinished messages cost model calls
    assert stored_ids(db, run_id) == ["T1", "T2", "T3", "T4", "T5"]
    job = job_of(db, run_id)
    assert job.status == "done" and job.worker == "w2" and job.attempts == 2
    assert run_of(db, run_id).status == "done"

    # the dead worker comes back and tries to report: fenced off, the new owner's outcome stands
    dead._finish(job.id, run_id, "failed", "late", [], 0.0)
    assert job_of(db, run_id).status == run_of(db, run_id).status == "done"


def test_running_job_with_a_live_heartbeat_is_not_taken(db):
    run_id = enqueue(db)
    first, _ = make_worker(db, name="a")
    second, _ = make_worker(db, name="b")
    assert first.claim() is not None
    assert second.claim() is None
    go_stale(db, run_id, seconds=30)  # older than a heartbeat, younger than stale_after_s
    assert second.claim() is None


def test_each_job_goes_to_one_worker(db):
    runs = [enqueue(db, 1) for _ in range(3)]
    workers = [make_worker(db, name=f"w{i}")[0] for i in range(3)]
    claimed = [w.claim() for w in workers]
    assert sorted(claimed) == sorted(job_of(db, r).id for r in runs)
    assert all(w.claim() is None for w in workers)


def test_job_that_keeps_crashing_is_failed_then_retry_resumes_it(db):
    run_id = enqueue(db)
    for i in range(3):  # three workers in a row die mid-run
        assert make_worker(db, name=f"dead{i}")[0].claim() is not None
        go_stale(db, run_id)
    worker, client = make_worker(db, name="w")
    assert worker.run_once()
    run = run_of(db, run_id)
    assert run.status == "failed" and "Stopped 3 times" in run.error and client.seen == []

    app = create_app(db, embedded_worker=False, lanes_factory=lambda: [])
    with TestClient(app) as c:
        assert c.post(f"/api/runs/{run_id}/retry").status_code == 200
        assert c.get(f"/api/runs/{run_id}").json()["status"] == "queued"
    assert worker.run_once()
    assert run_of(db, run_id).status == "done" and len(stored_ids(db, run_id)) == 5


def test_pipeline_error_fails_the_run_instead_of_leaving_it_running(db):
    run_id = enqueue(db)
    worker = Worker(db, lambda: [], policy="Policy.", cache_path=None, log=lambda _: None)  # no lanes: TriageRun raises
    assert worker.run_once()
    run = run_of(db, run_id)
    assert run.status == "failed" and "no provider lanes" in run.error and job_of(db, run_id).status == "failed"


def test_heartbeat_keeps_a_long_job_owned(db):
    run_id = enqueue(db)
    worker, _ = make_worker(db, heartbeat_s=0.01)
    job_id = worker.claim()
    go_stale(db, run_id)
    stop = threading.Event()
    beat = threading.Thread(target=worker._heartbeat, args=(job_id, stop))
    beat.start()
    time.sleep(0.2)
    stop.set()
    beat.join()
    assert make_worker(db, name="other")[0].claim() is None


def test_concurrent_workers_never_claim_the_same_job(db):
    """Separate engines (as separate processes would have), all claiming at once. On Postgres this exercises
    FOR UPDATE SKIP LOCKED; on SQLite the conditional UPDATE."""
    jobs = {job_of(db, enqueue(db, 1)).id for _ in range(12)}
    claimed: list[int] = []
    start = threading.Barrier(4)

    def claim_all(i):
        worker, _ = make_worker(Database(db.url), name=f"w{i}")
        start.wait()
        while (job_id := worker.claim()) is not None:
            claimed.append(job_id)
        worker.db.engine.dispose()

    threads = [threading.Thread(target=claim_all, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(claimed) == sorted(jobs)  # every job claimed exactly once
