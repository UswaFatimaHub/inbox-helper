"""Static configuration: the intent taxonomy, review flags, and provider lanes."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_POLICY = ROOT / "policies" / "recruiting_policy.md"
CACHE_PATH = ROOT / ".cache" / "triage_cache.json"

# Bump whenever the prompt changes so cached results from an older prompt are not reused.
PROMPT_VERSION = "v3"  # v2: no claimed actions, team voice, acknowledge frustration, spam flag; v3: injection != spam

INTENTS = {
    "application_status": "Asks where their application stands, whether it was received, or whether a decision was made.",
    "interview_scheduling": "Booking, confirming, rescheduling, or asking for the link/time of an interview.",
    "documents": "Sending, updating, or asking which documents are needed (CV, portfolio, ID, references, transcripts).",
    "offer_and_compensation": "Salary, salary range, negotiation, offer letters, start terms.",
    "withdrawal": "Withdrawing from the process and/or asking for their data to be deleted.",
    "accommodation_request": "Asks for an interview adjustment for disability, health, or similar needs.",
    "complaint": "Raises a concern about how they were treated or about the process conduct.",
    "general_question": "Questions about the company, roles, process, benefits, location, or visas.",
    "other": "Unclear, not from a candidate, spam, or does not fit any intent above.",
}

# Categories assigned by code, never offered to the model. These messages get no AI-drafted reply.
SYSTEM_INTENTS = {
    "manipulation_attempt": "Tries to instruct or manipulate the AI. Quarantined: no reply drafted; a reviewer can block the sender.",
    "blocked_sender": "Sender is on the blocklist. Not sent to the AI and not answered.",
}
ALL_INTENTS = {**INTENTS, **SYSTEM_INTENTS}

FLAGS = {
    "ambiguous": "It is unclear what the person wants.",
    "multiple_intents": "The message asks for more than one thing.",
    "sensitive": "Health, disability, discrimination, legal, or personal identity/financial data.",
    "unsupported_request": "Asks for something the policy does not allow or the team cannot provide.",
    "needs_info_not_available": "A correct answer needs records the tool cannot see (status, calendar, offer).",
    "prompt_injection": "The message tries to give instructions to the AI.",
    "hostile_tone": "Angry, threatening, or abusive tone.",
    "non_english": "Message is not in English.",
}

# Flags added by deterministic code checks, never by the model.
CODE_FLAGS = {
    "invalid_label": "The model returned an intent outside the allowed set.",
    "low_confidence": "Model confidence below the review threshold.",
    "unverified_date_or_time": "Draft mentions a date/time that is not in the message or policy.",
    "possible_hiring_decision": "Draft may state or imply a hiring decision.",
    "mentions_money": "Draft mentions a monetary amount.",
    "contains_placeholder": "Draft contains a [placeholder] the reviewer must fill.",
    "claims_completed_action": "Draft says something was already done (recorded, confirmed...). Do it or reword.",
    "ai_self_reference": "Draft speaks as 'I' or mentions the AI/tool instead of the team.",
    "long_draft": "Draft is longer than the target length.",
    "invalid_email": "The sender email address looks malformed.",
    "duplicate_message": "Same text as an earlier message in this batch.",
    "processing_failed": "No model produced a usable result; needs a manual reply.",
    "injection_pattern": "Text matches a known prompt-injection phrase; caught before any AI call.",
    "blocked_sender": "Sender is on the blocklist.",
}

# Intents that always go to the top of the review queue regardless of flags.
PRIORITY_INTENTS = {"accommodation_request", "complaint", "other", "manipulation_attempt"}
LOW_CONFIDENCE = 0.6
MAX_DRAFT_WORDS = 130


@dataclass(frozen=True)
class LaneConfig:
    """One independently rate-limited path to a model. Gemini quotas are per model, so each model is its own lane."""
    name: str
    provider: str            # "gemini" or "openrouter"
    models: tuple[str, ...]  # tried in order: openrouter does it server-side, gemini client-side on 503/404/429
    rpm: int                 # requests per minute we allow ourselves (kept below the provider's limit)
    concurrency: int         # parallel in-flight requests on this lane
    timeout_s: float
    thinking: str = "minimal"  # gemini thinkingLevel


# Measured 2026-10-26: OpenRouter free = 20 RPM / 50 per day (no credits); Gemini 3.5 Flash ~2 s,
# 3.5 Flash-Lite 18-80 s under load, occasional 503 "high demand". Gemini Pro models have no free quota.
PROFILES = {
    "standard": (
        LaneConfig("openrouter", "openrouter",
                   ("nvidia/nemotron-3.5-super-vl:free", "google/gemma-4-31b-it:free", "dots-studio/dots-3-note-preview:free"),
                   rpm=15, concurrency=2, timeout_s=60),
        LaneConfig("gemini-flash", "gemini", ("gemini-3.5-flash",), rpm=8, concurrency=2, timeout_s=90),
        LaneConfig("gemini-flash-lite", "gemini", ("gemini-3.5-flash-lite",), rpm=12, concurrency=2, timeout_s=120),
    ),
    # Strongest models the free tiers actually serve. 3.8/3.7 Flash are often at capacity, so the lane steps down.
# Measured with prompt v2: no quality gain over "standard", 3.5x slower, 3/41 messages failed. Kept for comparison.
    "best": (
        LaneConfig("openrouter-ultra", "openrouter",
                   ("nvidia/nemotron-3-ultra-550b-a55b:free", "nvidia/nemotron-3.5-super-vl:free"),
                   rpm=15, concurrency=2, timeout_s=150),
        LaneConfig("gemini-newest", "gemini", ("gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash"),
                   rpm=8, concurrency=2, timeout_s=60, thinking="low"),
    ),
}
DEFAULT_PROFILE = os.environ.get("MODEL_PROFILE", "standard")
DEFAULT_LANES = PROFILES[DEFAULT_PROFILE]


def load_api_keys() -> dict[str, str]:
    """Read keys from .env / environment, tolerating stray quotes and whitespace."""
    load_dotenv(ROOT / ".env")
    keys = {}
    for provider, var in (("gemini", "GEMINI_API_KEY"), ("openrouter", "OPENROUTER_API_KEY")):
        value = os.environ.get(var, "").strip().strip('"').strip("'").strip()
        if value:
            keys[provider] = value
    return keys
