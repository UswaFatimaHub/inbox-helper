"""Static configuration: the intent taxonomy, review flags, and provider lanes."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_POLICY = ROOT / "policies" / "recruiting_policy.md"
CACHE_PATH = ROOT / ".cache" / "triage_cache.json"

# A label recorded on every draft and eval run; bump it when the prompt changes so results can be compared.
# The cache does not depend on it: cache keys hash the prompt text itself (pipeline.TriageRun._cache_key).
PROMPT_VERSION = "v8"  # v2: no claimed actions, team voice, acknowledge frustration, spam flag; v3: injection != spam
#                        v4: no_reply_needed for automated mail and spam (no draft)
#                        v5: body only; greeting and sign-off are added by code (reply.py)
#                        v6: also reports the candidate's language, so code picks a greeting in that language
#                        v7: a person needing an answer about something unrelated is "other", never no_reply_needed;
#                            passwords count as sensitive
#                        v8: the model no longer chooses no_reply_needed (it filed real people under it, on every
#                            model tried); a sender rule in code decides it instead

INTENTS = {
    "application_status": "Asks where their application stands, whether it was received, or whether a decision was made.",
    "interview_scheduling": "Booking, confirming, rescheduling, or asking for the link/time of an interview.",
    "documents": "Sending, updating, or asking which documents are needed (CV, portfolio, ID, references, transcripts).",
    "offer_and_compensation": "Salary, salary range, negotiation, offer letters, start terms.",
    "withdrawal": "Withdrawing from the process and/or asking for their data to be deleted.",
    "accommodation_request": "Asks for an interview adjustment for disability, health, or similar needs.",
    "complaint": "Raises a concern about how they were treated or about the process conduct.",
    "general_question": "Questions about the company, roles, process, benefits, location, or visas.",
    "other": "Unclear, or a person asking something that does not fit any intent above.",
}

# Automated mail nobody answers. Assigned by code from the sender (checks.automated_sender), never by the model:
# with the model choosing it (prompts v4-v7), every model tried sometimes filed a real person under it. No draft,
# no queue priority; a reviewer confirms it with "Close, no reply". Not quarantine, so not in SYSTEM_INTENTS.
NO_REPLY_INTENT = "no_reply_needed"
NO_REPLY_DESCRIPTION = "Automated email from a no-reply sender (Google). Not sent to the AI; a reviewer closes it."
# Domains (and their subdomains) whose no-reply addresses (noreply@, no-reply@, noreply-accounts@...) are closed
# without a reply. Only the test inbox's own Google notifications so far; a person at these domains still gets one.
NO_REPLY_SENDER_DOMAINS = ("google.com",)

# Categories assigned by code, never offered to the model. These messages get no AI-drafted reply.
SYSTEM_INTENTS = {
    "manipulation_attempt": "Tries to instruct or manipulate the AI. Quarantined: no reply drafted; a reviewer can block the sender.",
    "blocked_sender": "Sender is on the blocklist. Not sent to the AI and not answered.",
}
ALL_INTENTS = {**INTENTS, NO_REPLY_INTENT: NO_REPLY_DESCRIPTION, **SYSTEM_INTENTS}

FLAGS = {
    "ambiguous": "It is unclear what the person wants.",
    "multiple_intents": "The message asks for more than one thing.",
    "sensitive": "Health, disability, discrimination, legal, passwords or login details, or personal identity/financial data.",
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
    "injection_pattern": "Text matches a known prompt-injection phrase.",
    "blocked_sender": "Sender is on the blocklist.",
    "personal_data_hidden": "Passwords, ID, bank, card, passport or phone numbers or email addresses were hidden from the AI.",
}

# Flags that stay meaningful on a quarantined message. Others (low_confidence, needs_info_not_available, ...)
# describe the AI's reading of a request we refuse to answer, so they are dropped.
QUARANTINE_KEEP_FLAGS = {"prompt_injection", "injection_pattern", "blocked_sender", "non_english", "hostile_tone",
                         "sensitive", "invalid_email", "duplicate_message"}

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
# 2026-10-30: Nemotron dropped (it swapped results between messages in a batch). Of the free OpenRouter
# models, only dots-3-note-preview answered: Gemma 4 31B/26B and Xing 4.0 gave 429, Flint 503, no Qwen is free.
# dots takes 35-65 s per batch of 5, hence the long timeout.
PROFILES = {
    "standard": (
        LaneConfig("openrouter", "openrouter", ("dots-studio/dots-3-note-preview:free",),
                   rpm=15, concurrency=2, timeout_s=150),
        LaneConfig("gemini-flash", "gemini", ("gemini-3.5-flash",), rpm=8, concurrency=2, timeout_s=90),
        LaneConfig("gemini-flash-lite", "gemini", ("gemini-3.5-flash-lite",), rpm=12, concurrency=2, timeout_s=120),
    ),
    # Strongest models the free tiers actually serve. 3.8/3.7 Flash are often at capacity, so the lane steps down.
# Measured with prompt v2: no quality gain over "standard", 3.5x slower, 3/41 messages failed. Kept for comparison.
# Its Nemotron Ultra lane was removed on 2026-10-30 along with Nemotron in "standard".
    "best": (
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
