"""Parse model output and run deterministic checks on it.

The model is not trusted to follow the rules: labels are validated against the allowed set, and drafts are
scanned for facts the policy forbids (dates/times not in the source, hiring decisions, money amounts).
"""
import json
import re
from dataclasses import dataclass, field

from .config import FLAGS, INTENTS, LOW_CONFIDENCE, MAX_DRAFT_WORDS, NO_REPLY_INTENT


class ParseError(Exception):
    """The model response could not be used."""


@dataclass
class Triage:
    intent: str
    secondary_intent: str | None
    confidence: float
    flags: list[str]
    reason: str
    draft_reply: str
    code_flags: list[str] = field(default_factory=list)


def parse_batch_response(text: str, expected_ids: list[str]) -> dict[str, dict]:
    """Return {message_id: raw item} for the expected ids the model answered. Unknown ids are dropped."""
    cleaned = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ParseError(f"model returned invalid JSON ({e.msg} at char {e.pos})") from None
    items = data.get("results") if isinstance(data, dict) else data
    if isinstance(data, dict) and items is None and "message_id" in data:
        items = [data]  # single-message batch answered without the wrapper
    if not isinstance(items, list):
        raise ParseError("model JSON has no 'results' list")
    wanted = set(expected_ids)
    found = {}
    for item in items:
        if isinstance(item, dict):
            mid = str(item.get("message_id", "")).strip()
            # a result needs a draft, unless the model says no reply is needed
            has_draft = str(item.get("draft_reply") or "").strip() or str(item.get("intent") or "").strip().lower() == NO_REPLY_INTENT
            if mid in wanted and mid not in found and has_draft:
                found[mid] = item
    if not found:
        raise ParseError("model JSON contained no usable result for any requested message")
    return found


def normalize(raw: dict) -> Triage:
    code_flags = []
    intent = str(raw.get("intent") or "").strip().lower()
    if intent not in INTENTS:
        code_flags.append("invalid_label")
        intent = "other"
    secondary = str(raw.get("secondary_intent") or "").strip().lower() or None
    if secondary not in INTENTS or secondary == intent:
        secondary = None
    try:
        confidence = min(max(float(raw.get("confidence")), 0.0), 1.0)
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < LOW_CONFIDENCE:
        code_flags.append("low_confidence")
    raw_flags = raw.get("flags") if isinstance(raw.get("flags"), list) else []
    flags = sorted({str(f).strip().lower() for f in raw_flags} & FLAGS.keys())
    return Triage(intent=intent, secondary_intent=secondary, confidence=round(confidence, 2), flags=flags,
                  reason=str(raw.get("reason") or "").strip()[:300],
                  draft_reply=str(raw.get("draft_reply") or "").strip(), code_flags=code_flags)


_MONTH = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
DATE_TIME_PATTERNS = [
    re.compile(r"\b(?:mon|tues|wednes|thurs|fri|satur|sun)day\b", re.I),
    re.compile(rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH}\b", re.I),
    re.compile(rf"\b{_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\b", re.I),
    re.compile(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", re.I),
    re.compile(r"\b\d{1,2}:\d{2}\b"),
    re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"),
]
DECISION_PATTERNS = [
    re.compile(r"\byou(?:'ve| have)? been (?:selected|hired|shortlisted|rejected|accepted|offered)\b", re.I),
    re.compile(r"\byou(?:'re| are) (?:hired|rejected|successful|unsuccessful)\b", re.I),
    re.compile(r"\b(?:pleased|happy|delighted) to (?:offer|inform you that you)\b", re.I),
    re.compile(r"\b(?:not|won't|will not|unable to|decided not to) (?:be )?(?:moving|move|proceed(?:ing)?) forward with your\b", re.I),
    re.compile(r"\bunfortunately,? (?:we|your application)\b", re.I),
]
MONEY_PATTERN = re.compile(
    r"(?:[$€£]|\b(?:usd|pkr|rs\.?|rupees)\s?)\s?\d|\b\d[\d,.]*\s?(?:k|m|million|lakh)?\s?(?:pkr|usd|rupees|dollars)\b",
    re.I)
PLACEHOLDER_PATTERN = re.compile(r"\[[^\]\n]{1,40}\]")
_DONE = r"(?:recorded|noted|logged|processed|confirmed|deleted|removed|updated|added|forwarded|escalated|passed on|shared|scheduled|rescheduled|cancelled|withdrawn)"
COMPLETED_ACTION_PATTERNS = [
    re.compile(rf"\b(?:has|have)\s+(?:now\s+|already\s+)?been\s+{_DONE}\b", re.I),
    re.compile(rf"\b(?:we|i)(?:'ve|’ve| have)\s+(?:now\s+|already\s+)?{_DONE}\b", re.I),
    re.compile(rf"\b(?:we|i)\s+(?:just\s+)?{_DONE}\s+(?:your|the)\b", re.I),
    re.compile(rf"\bhave\s+(?:now\s+|already\s+)?{_DONE}\s+(?:it|this|that|your|the)\b", re.I),  # "...and have escalated it"
]
# Case-sensitive "I" as a word: replies speak as the team. Plus explicit mentions of being an AI/tool.
SELF_REFERENCE_PATTERNS = [
    re.compile(r"(?<![\w'’])I(?:'m|’m|'ve|’ve|'ll|’ll)?(?![\w'’])"),
    re.compile(r"\b(?:as an ai|language model|this tool|this assistant|cannot see (?:application )?records)\b", re.I),
]


# Phrases that only make sense as instructions to an AI. Kept narrow on purpose: a false positive quarantines a real
# candidate's message, so "please ignore my previous email" must NOT match. The model's own prompt_injection flag is
# the second layer for anything these miss (other languages, paraphrases).
INJECTION_PATTERNS = [
    re.compile(r"\b(?:ignore|disregard|forget|override)\s+(?:all\s+|any\s+)?(?:of\s+)?(?:the\s+|your\s+)?"
               r"(?:previous|prior|above|earlier|preceding|system)\s+(?:instructions?|prompts?|rules|guidelines|directions)\b", re.I),
    re.compile(r"\b(?:ignore|disregard|forget|override)\s+(?:all\s+)?your\s+(?:instructions|rules|guidelines|programming)\b", re.I),
    re.compile(r"\byou\s+are\s+now\s+(?:a|an|the)\s+(?:hiring|recruit|manager|admin|system|assistant|ai)", re.I),
    re.compile(r"\b(?:system|developer)\s+prompt\b", re.I),
    re.compile(r"^\s*(?:\[(?:system|assistant|admin)\]|(?:system|assistant)\s*:)", re.I | re.M),
    re.compile(r"\b(?:new|updated)\s+instructions\s*:", re.I),
    re.compile(r"\b(?:ai|assistant|chatbot|language model|llm)\s*[:,]\s*(?:ignore|disregard|you must|from now on|add a note|mark)\b", re.I),
    re.compile(r"\bjailbreak\b|\bDAN mode\b", re.I),
]


def detect_injection(text: str) -> bool:
    return any(p.search(text) for p in INJECTION_PATTERNS)


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def check_draft(draft: str, source_text: str, policy_text: str) -> list[str]:
    """Flags for a draft. Dates/times are allowed only if they literally appear in the message or policy."""
    flags = []
    allowed = _norm(source_text + " " + policy_text)
    for pattern in DATE_TIME_PATTERNS:
        if any(_norm(m.group(0)) not in allowed for m in pattern.finditer(draft)):
            flags.append("unverified_date_or_time")
            break
    if any(p.search(draft) for p in DECISION_PATTERNS):
        flags.append("possible_hiring_decision")
    if MONEY_PATTERN.search(draft):
        flags.append("mentions_money")
    if PLACEHOLDER_PATTERN.search(draft):
        flags.append("contains_placeholder")
    if any(p.search(draft) for p in COMPLETED_ACTION_PATTERNS):
        flags.append("claims_completed_action")
    if any(p.search(draft) for p in SELF_REFERENCE_PATTERNS):
        flags.append("ai_self_reference")
    if len(draft.split()) > MAX_DRAFT_WORDS:
        flags.append("long_draft")
    return flags
