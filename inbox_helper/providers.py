"""Thin HTTP clients for Gemini and OpenRouter, plus a per-lane rate limiter."""
import threading
import time
from dataclasses import dataclass

import requests

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class ProviderError(Exception):
    """A request failed. `disable_lane` means retrying on this lane is pointless (bad key, model gone, daily cap)."""

    def __init__(self, message: str, *, disable_lane: bool = False, retry_after: float | None = None,
                 status: int | None = None):
        super().__init__(message)
        self.disable_lane = disable_lane
        self.status = status
        self.retry_after = retry_after


@dataclass
class Completion:
    text: str
    model: str
    latency_s: float


class RateLimiter:
    """Spaces request starts at least 60/rpm seconds apart; shared by all workers of one lane."""

    def __init__(self, rpm: float):
        self.interval = 60.0 / rpm
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next)
            self._next = start + self.interval
        if start > now:
            time.sleep(start - now)

    def back_off(self, seconds: float) -> None:
        with self._lock:
            self._next = max(self._next, time.monotonic() + seconds)


def _post(url: str, headers: dict, payload: dict, timeout: float) -> tuple[dict, float]:
    start = time.monotonic()
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except requests.Timeout:
        raise ProviderError(f"timed out after {timeout:.0f}s") from None
    except requests.RequestException as e:
        raise ProviderError(f"network error: {e.__class__.__name__}") from None
    latency = time.monotonic() - start
    if resp.status_code != 200:
        _raise_for_status(resp)
    try:
        return resp.json(), latency
    except ValueError:
        raise ProviderError("response was not JSON") from None


def _raise_for_status(resp: requests.Response) -> None:
    code, body = resp.status_code, resp.text[:300]
    try:  # both providers wrap errors as {"error": {"message": ...}}
        body = str(resp.json()["error"]["message"])[:300]
    except (ValueError, KeyError, TypeError):
        pass
    if code in (401, 403):
        raise ProviderError(f"HTTP {code}: API key rejected", disable_lane=True, status=code)
    if code == 404:
        raise ProviderError(f"HTTP 404: model not available ({body})", disable_lane=True, status=code)
    if code == 429:
        daily = any(s in body.lower() for s in ("per day", "per-day", "daily", "perday"))
        retry_after = resp.headers.get("Retry-After")
        raise ProviderError(f"HTTP 429: rate limited{' (daily quota)' if daily else ''}",
                            disable_lane=daily,
                            retry_after=float(retry_after) if retry_after and retry_after.isdigit() else 15.0,
                            status=code)
    raise ProviderError(f"HTTP {code}: {body}", status=code)


class GeminiClient:
    def __init__(self, api_key: str, models: tuple[str, ...], timeout_s: float, thinking: str = "minimal"):
        self.api_key, self.models, self.timeout_s, self.thinking = api_key, models, timeout_s, thinking

    def complete(self, system: str, user: str) -> Completion:
        """Try each model in order; a busy/missing/over-quota model falls through to the next one."""
        last: ProviderError | None = None
        for model in self.models:
            try:
                return self._complete(model, system, user)
            except ProviderError as e:
                last = e
                if e.status not in (404, 429, 503):
                    raise
        assert last is not None
        raise last

    def _complete(self, model: str, system: str, user: str) -> Completion:
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
                "thinkingConfig": {"thinkingLevel": self.thinking},  # "minimal" measured as a big latency win
            },
        }
        data, latency = _post(GEMINI_URL.format(model=model),
                              {"x-goog-api-key": self.api_key}, payload, self.timeout_s)
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError):
            first = (data.get("candidates") or [{}])[0]
            reason = (data.get("promptFeedback") or {}).get("blockReason") or first.get("finishReason")
            raise ProviderError(f"no content in response (reason: {reason})") from None
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        return Completion(text, model, latency)


class OpenRouterClient:
    def __init__(self, api_key: str, models: tuple[str, ...], timeout_s: float):
        self.api_key, self.models, self.timeout_s = api_key, models, timeout_s

    def complete(self, system: str, user: str) -> Completion:
        payload = {
            "models": list(self.models),  # OpenRouter tries these in order server-side
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "X-Title": "Inbox Helper prototype"}
        data, latency = _post(OPENROUTER_URL, headers, payload, self.timeout_s)
        if "error" in data:
            raise ProviderError(f"provider error: {str(data['error'])[:200]}")
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError):
            raise ProviderError("no choices in response") from None
        return Completion(text, data.get("model", self.models[0]), latency)
