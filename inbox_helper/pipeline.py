"""Batch messages, spread batches across provider lanes, and assemble exactly one result per message.

Scheduling: every lane has its own rate limiter and a few worker threads pulling from one shared queue, so a
fast lane naturally takes more batches and a slow or failing lane cannot hold up the run. A failed batch is
retried on a lane that has not tried it yet; a batch whose output cannot be parsed is split into single messages.
"""
import hashlib
import json
import queue
import sys
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

from .checks import ParseError, automated_sender, check_draft, detect_injection, normalize, parse_batch_response
from .config import NO_REPLY_INTENT, PRIORITY_INTENTS, PROMPT_VERSION, QUARANTINE_KEEP_FLAGS, LaneConfig
from .loader import Message
from .prompt import build_system_prompt, build_user_prompt
from .providers import Completion, GeminiClient, OpenRouterClient, ProviderError, RateLimiter
from .redact import redact
from .reply import compose, greeting_language, language_of, strip_salutations

# Flags that move a draft to the top of the review queue.
PRIORITY_FLAGS = {"ambiguous", "sensitive", "unsupported_request", "prompt_injection", "injection_pattern", "hostile_tone",
                  "invalid_label", "low_confidence", "unverified_date_or_time", "possible_hiring_decision",
                  "mentions_money", "contains_placeholder", "claims_completed_action", "ai_self_reference",
                  "processing_failed"}


@dataclass
class Result:
    message_id: str
    received_at: str
    candidate_name: str
    candidate_email: str
    role: str
    subject: str
    body: str
    intent: str
    secondary_intent: str | None
    confidence: float
    flags: list[str]
    priority_review: bool
    reason: str
    draft_reply: str
    lane: str
    model: str
    prompt_version: str
    latency_s: float | None
    error: str | None
    processed_at: str
    # Review fields: filled in by a human; nothing is ever sent by this tool.
    review_status: str = "pending"
    final_reply: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    draft_body: str = ""  # draft_reply without greeting and sign-off: what the AI wrote (reply.py)
    language: str = "en"  # the candidate's language; picks the greeting and sign-off


class Client(Protocol):
    def complete(self, system: str, user: str) -> Completion: ...


@dataclass
class Lane:
    name: str
    client: Client
    limiter: RateLimiter
    concurrency: int = 1
    disabled: bool = False
    calls: int = 0
    failures: int = 0


@dataclass
class Job:
    messages: list[Message]
    attempts: int = 0
    tried: set[str] = field(default_factory=set)


def build_lanes(configs: tuple[LaneConfig, ...], keys: dict[str, str], log: Callable[[str], None]) -> list[Lane]:
    lanes = []
    for c in configs:
        if c.provider not in keys:
            log(f"skipping lane {c.name}: no API key for {c.provider}")
            continue
        client = (GeminiClient(keys["gemini"], c.models, c.timeout_s, c.thinking) if c.provider == "gemini"
                  else OpenRouterClient(keys["openrouter"], c.models, c.timeout_s))
        lanes.append(Lane(c.name, client, RateLimiter(c.rpm), c.concurrency))
    return lanes


class Cache:
    """JSON file of validated model outputs, keyed by the exact prompt text the model saw (see _cache_key)."""

    def __init__(self, path: Path | None):
        self.path = path
        self._data: dict = {}
        self._lock = threading.Lock()
        if path and path.exists():
            try:
                self._data = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                self._data = {}

    def get(self, key: str) -> dict | None:
        return self._data.get(key)

    def put(self, key: str, value: dict) -> None:
        with self._lock:
            self._data[key] = value

    def save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=1), encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stderr_log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


class TriageRun:
    def __init__(self, lanes: list[Lane], policy: str, cache: Cache | None = None, batch_size: int = 5,
                 max_attempts: int = 3, log: Callable[[str], None] = _stderr_log,
                 on_result: Callable[[Result], None] | None = None, blocked_senders: frozenset[str] = frozenset()):
        if not lanes:
            raise ValueError("no provider lanes available (check API keys in .env)")
        self.lanes, self.policy, self.batch_size, self.max_attempts = lanes, policy, max(1, batch_size), max_attempts
        self.cache = cache or Cache(None)
        self.system = build_system_prompt(policy)
        self._system_hash = hashlib.sha256(self.system.encode()).hexdigest()
        self._t0 = time.monotonic()
        self._log = log
        self._on_result = on_result
        self.blocked_senders = frozenset(e.strip().lower() for e in blocked_senders)
        self._queue: queue.Queue[Job] = queue.Queue()
        self._lock = threading.Lock()
        self._outstanding = 0
        self._done = threading.Event()
        self._results: dict[str, Result] = {}
        self._for_model: dict[str, Message] = {}   # message_id -> the copy the AI sees, identifiers hidden
        self._hidden: dict[str, list[str]] = {}    # message_id -> kinds of identifiers hidden
        self._last_error: dict[str, str] = {}

    # ---- public -------------------------------------------------------------------------------------------
    def run(self, messages: list[Message]) -> list[Result]:
        for m in messages:
            subject, body = redact(m.subject), redact(m.body)
            self._for_model[m.message_id] = replace(m, subject=subject.text, body=body.text)
            if kinds := sorted(set(subject.kinds + body.kinds)):
                self._hidden[m.message_id] = kinds
        if self._hidden:
            self.log(f"identifiers hidden from the AI in {len(self._hidden)} message(s)")
        todo = []
        for m in messages:
            if m.candidate_email.strip().lower() in self.blocked_senders:
                self._store(self._quarantined_result(m, "blocked_sender", "Sender is on the blocklist; not processed."))
                continue
            if automated_sender(m.candidate_email):
                self._store(self._no_reply_result(m))
                continue
            if detect_injection(f"{m.subject}\n{m.body}"):  # never send known injection text to the model
                self._store(self._quarantined_result(
                    m, "manipulation_attempt", "Matches a known prompt-injection phrase; not sent to the AI."))
                continue
            hit = self.cache.get(self._cache_key(m))
            if hit:
                self._record(m, hit["raw"], "cache", hit["model"], None)
            else:
                todo.append(m)
        if len(todo) < len(messages):
            self.log(f"{len(messages) - len(todo)} message(s) handled without a model call "
                     "(cache, blocklist, automated sender, injection)")
        if todo:
            for i in range(0, len(todo), self.batch_size):
                self._put(Job(todo[i:i + self.batch_size]))
            self.log(f"{len(todo)} message(s) in {self._outstanding} batch(es) across lanes: "
                     + ", ".join(f"{l.name} x{l.concurrency}" for l in self.lanes))
            self._run_workers()
        for m in messages:  # guarantee: one result per valid message, even when every provider failed
            if m.message_id not in self._results:
                self._results[m.message_id] = self._failed_result(
                    m, self._last_error.get(m.message_id, "no provider lane was available"))
                self._emit(self._results[m.message_id])
        try:
            self.cache.save()
        except OSError as e:  # results are already stored; a cache that cannot be written only costs calls later
            self.log(f"could not save the cache: {e}")
        return [self._results[m.message_id] for m in messages]

    def log(self, msg: str) -> None:
        self._log(f"[{time.monotonic() - self._t0:6.1f}s] {msg}")

    # ---- scheduling ---------------------------------------------------------------------------------------
    def _put(self, job: Job) -> None:
        with self._lock:
            self._outstanding += 1
        self._queue.put(job)

    def _finish(self) -> None:
        with self._lock:
            self._outstanding -= 1
            if self._outstanding == 0:
                self._done.set()

    def _run_workers(self) -> None:
        threads = [threading.Thread(target=self._worker, args=(lane,), daemon=True)
                   for lane in self.lanes for _ in range(lane.concurrency)]
        for t in threads:
            t.start()
        while not self._done.is_set() and any(t.is_alive() for t in threads):
            self._done.wait(0.5)
        if not self._done.is_set():
            self.log("all lanes disabled; remaining messages will be marked processing_failed")
        self._done.set()
        for t in threads:
            t.join()

    def _worker(self, lane: Lane) -> None:
        while not self._done.is_set() and not lane.disabled:
            try:
                job = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if lane.name in job.tried and any(l.name not in job.tried and not l.disabled for l in self.lanes):
                self._queue.put(job)  # leave it for a lane that has not failed it yet
                time.sleep(0.05)
                continue
            self._attempt(lane, job)

    def _attempt(self, lane: Lane, job: Job) -> None:
        ids = [m.message_id for m in job.messages]
        label = ids[0] if len(ids) == 1 else f"{ids[0]}..{ids[-1]} ({len(ids)})"
        lane.limiter.wait()
        lane.calls += 1
        try:
            prompt = build_user_prompt([self._model_copy(m) for m in job.messages])
            completion = lane.client.complete(self.system, prompt)
            found = parse_batch_response(completion.text, ids)
        except (ProviderError, ParseError) as e:
            self._on_failure(lane, job, e, label)
            return
        self.log(f"{lane.name}: {label} ok in {completion.latency_s:.1f}s via {completion.model}")
        for m in job.messages:
            if m.message_id in found:
                raw = found[m.message_id]
                self.cache.put(self._cache_key(m), {"raw": raw, "model": completion.model})
                self._record(m, raw, lane.name, completion.model, round(completion.latency_s, 2))
        missing = [m for m in job.messages if m.message_id not in found]
        if missing:
            self.log(f"{lane.name}: model skipped {[m.message_id for m in missing]}; retrying them individually")
            for m in missing:
                self._last_error[m.message_id] = f"{lane.name}: model omitted this message"
                if job.attempts + 1 < self.max_attempts:
                    self._put(Job([m], job.attempts + 1, job.tried | {lane.name}))
        self._finish()

    def _on_failure(self, lane: Lane, job: Job, err: Exception, label: str) -> None:
        lane.failures += 1
        self.log(f"{lane.name}: {label} failed: {err}")
        for m in job.messages:
            self._last_error[m.message_id] = f"{lane.name}: {err}"
        if isinstance(err, ProviderError):
            if err.disable_lane and not lane.disabled:
                lane.disabled = True
                self.log(f"{lane.name}: disabled for the rest of this run")
            if err.retry_after:
                lane.limiter.back_off(err.retry_after)
        attempts, tried = job.attempts + 1, job.tried | {lane.name}
        if isinstance(err, ParseError) and len(job.messages) > 1:
            for m in job.messages:  # one bad output should not sink the whole batch; each single gets a fresh budget
                self._put(Job([m], 0, set(tried)))
        elif attempts < self.max_attempts:
            self._put(Job(job.messages, attempts, tried))
        self._finish()

    # ---- results ------------------------------------------------------------------------------------------
    def _cache_key(self, m: Message) -> str:
        # Everything the model is shown for this message, so any edit to the prompt, taxonomy or policy misses the
        # cache without anyone having to bump PROMPT_VERSION. The id is blanked: the same text under another id hits.
        blob = json.dumps([self._system_hash, build_user_prompt([replace(self._model_copy(m), message_id="")])])
        return hashlib.sha256(blob.encode()).hexdigest()

    def _record(self, m: Message, raw: dict, lane: str, model: str, latency: float | None) -> None:
        t = normalize(raw)
        if "prompt_injection" in t.flags:  # the model spotted manipulation the patterns missed: quarantine, drop draft
            result = self._quarantined_result(
                m, "manipulation_attempt", t.reason or "The model flagged this message as prompt injection.",
                extra_flags=t.flags, confidence=t.confidence, lane=lane, model=model, latency=latency)
            self._store(result)
            return
        flags = set(t.flags + t.code_flags + m.warnings)
        # the model is told to write the body only; this enforces it. Its own greeting, if any, still tells the
        # language when it did not report one.
        language = language_of(t.language or greeting_language(t.draft_reply))
        body = strip_salutations(t.draft_reply, m.candidate_name)
        t.draft_reply = compose(body, m.candidate_name, language=language)
        flags.update(check_draft(t.draft_reply, f"{m.subject} {m.body}", self.policy))
        result = Result(
            **self._input_fields(m), intent=t.intent, secondary_intent=t.secondary_intent,
            confidence=t.confidence, flags=sorted(flags),
            priority_review=t.intent in PRIORITY_INTENTS or bool(flags & PRIORITY_FLAGS),
            reason=t.reason, draft_reply=t.draft_reply, draft_body=body, language=language, lane=lane, model=model,
            prompt_version=PROMPT_VERSION,
            latency_s=latency, error=None, processed_at=_now())
        self._store(result)

    def _store(self, result: Result) -> None:
        with self._lock:
            if result.message_id in self._results:
                return
            self._results[result.message_id] = result
        self._emit(result)

    def _quarantined_result(self, m: Message, intent: str, reason: str, *, extra_flags: list[str] = (),
                            secondary: str | None = None, confidence: float = 1.0, lane: str = "rules",
                            model: str = "none", latency: float | None = None) -> Result:
        """No reply is drafted. Blocked senders are closed immediately; manipulation attempts wait for a reviewer."""
        flags = {f for f in extra_flags if f in QUARANTINE_KEEP_FLAGS} | set(m.warnings)
        if intent == "blocked_sender":
            flags.add("blocked_sender")
        else:
            flags.add("prompt_injection")
            if lane == "rules":
                flags.add("injection_pattern")
        return Result(**self._input_fields(m), intent=intent, secondary_intent=secondary, confidence=round(confidence, 2),
                      flags=sorted(flags), priority_review=intent == "manipulation_attempt", reason=reason,
                      draft_reply="", lane=lane, model=model, prompt_version=PROMPT_VERSION, latency_s=latency,
                      error=None, processed_at=_now(),
                      review_status="blocked" if intent == "blocked_sender" else "pending")

    def _no_reply_result(self, m: Message) -> Result:
        """Automated mail from a no-reply sender: no AI call, no draft, no priority. A reviewer closes it."""
        return Result(**self._input_fields(m), intent=NO_REPLY_INTENT, secondary_intent=None, confidence=1.0,
                      flags=sorted(set(m.warnings)), priority_review=False,
                      reason=f"Automated email from {m.candidate_email.strip().lower()}; not sent to the AI.",
                      draft_reply="", lane="rules", model="none", prompt_version=PROMPT_VERSION, latency_s=None,
                      error=None, processed_at=_now())

    def _model_copy(self, m: Message) -> Message:
        return self._for_model.get(m.message_id) or replace(m, subject=redact(m.subject).text, body=redact(m.body).text)

    def _emit(self, result: Result) -> None:
        if result.message_id in self._hidden:  # identity/financial data: always a sensitive message
            result.flags = sorted({*result.flags, "personal_data_hidden", "sensitive"})
            result.priority_review = True
        if self._on_result:
            try:
                self._on_result(result)
            except Exception as e:  # a storage hiccup must not kill the worker thread
                self.log(f"on_result failed for {result.message_id}: {e}")

    def _failed_result(self, m: Message, error: str) -> Result:
        return Result(**self._input_fields(m), intent="other", secondary_intent=None, confidence=0.0,
                      flags=sorted({"processing_failed", *m.warnings}), priority_review=True,
                      reason="No model produced a usable result.", draft_reply="", lane="none", model="none",
                      prompt_version=PROMPT_VERSION, latency_s=None, error=error, processed_at=_now())

    @staticmethod
    def _input_fields(m: Message) -> dict:
        return dict(message_id=m.message_id, received_at=m.received_at, candidate_name=m.candidate_name,
                    candidate_email=m.candidate_email, role=m.role, subject=m.subject, body=m.body)
