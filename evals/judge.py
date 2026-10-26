"""deepeval judge model built on the app's own provider clients, so no extra SDK or key is needed.

Lanes are tried in order and the next one is used only when a call fails, so in a healthy run one model judges
every case and scores stay comparable. The models that actually judged are counted and printed in the report.
"""
import asyncio
import threading
import time
from collections import Counter

from deepeval.metrics.utils import trimAndLoadJson
from deepeval.models import DeepEvalBaseLLM

from inbox_helper.config import LaneConfig
from inbox_helper.pipeline import Lane, build_lanes
from inbox_helper.providers import ProviderError

# Gemini first: OpenRouter's free tier is 50 requests/day, which a full judged run would use up (and the app shares it).
JUDGE_PROFILES = {
    "gemini": (
        LaneConfig("judge-gemini-flash", "gemini", ("gemini-3.5-flash",), rpm=8, concurrency=1, timeout_s=90,
                   thinking="low"),
        LaneConfig("judge-gemini-flash-lite", "gemini", ("gemini-3.5-flash-lite",), rpm=12, concurrency=1,
                   timeout_s=120, thinking="low"),
    ),
    # A newer model than the one that writes the drafts, to reduce self-preference bias. Often at capacity.
    "gemini-newest": (
        LaneConfig("judge-gemini-newest", "gemini", ("gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash"),
                   rpm=8, concurrency=1, timeout_s=90, thinking="low"),
        LaneConfig("judge-gemini-flash", "gemini", ("gemini-3.5-flash",), rpm=8, concurrency=1, timeout_s=90,
                   thinking="low"),
    ),
    "openrouter": (
        LaneConfig("judge-openrouter", "openrouter",
                   ("nvidia/nemotron-3-ultra-550b-a55b:free", "nvidia/nemotron-3.5-super-vl:free"),
                   rpm=15, concurrency=1, timeout_s=150),
    ),
}

JUDGE_SYSTEM = ("You are a careful, impartial evaluator of draft replies that a recruiting team may send to job "
                "candidates. Follow the evaluation instructions exactly and answer only with the JSON they ask for.")


class LaneJudge(DeepEvalBaseLLM):
    def __init__(self, lanes: list[Lane], log=print, rounds: int = 4):
        self.lanes, self.log, self.rounds = lanes, log, rounds
        self.models_used: Counter[str] = Counter()
        self.failures = 0
        self._lock = threading.Lock()
        super().__init__(model="inbox-lanes:" + "+".join(l.name for l in lanes))

    def load_model(self):
        return self

    def get_model_name(self) -> str:
        return "inbox-lanes(" + ", ".join(l.name for l in self.lanes) + ")"

    def generate(self, prompt, schema=None, **kwargs):
        text = self._complete(prompt if isinstance(prompt, str) else str(prompt))
        if schema is None:
            return text
        try:
            return schema.model_validate(trimAndLoadJson(text))
        except Exception:  # hand the raw text back; deepeval parses it itself and records a clear metric error
            return text

    async def a_generate(self, prompt, schema=None, **kwargs):
        return await asyncio.to_thread(self.generate, prompt, schema)

    def _complete(self, prompt: str) -> str:
        last: Exception | None = None
        for attempt in range(self.rounds):
            active = [l for l in self.lanes if not l.disabled]
            if not active:
                break
            for lane in active:
                lane.limiter.wait()
                lane.calls += 1
                try:
                    completion = lane.client.complete(JUDGE_SYSTEM, prompt)
                except ProviderError as e:
                    lane.failures += 1
                    last = e
                    with self._lock:
                        self.failures += 1
                    if e.disable_lane and not lane.disabled:
                        lane.disabled = True
                        self.log(f"judge lane {lane.name} disabled: {e}")
                    if e.retry_after:
                        lane.limiter.back_off(e.retry_after)
                    continue
                with self._lock:
                    self.models_used[completion.model] += 1
                return completion.text
            time.sleep(min(30.0, 5.0 * 2 ** attempt))
        raise RuntimeError(f"judge call failed on every lane: {last}")


def build_judge(profile: str, keys: dict[str, str], log=print) -> LaneJudge | None:
    lanes = build_lanes(JUDGE_PROFILES[profile], keys, log)
    return LaneJudge(lanes, log) if lanes else None
