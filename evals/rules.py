"""Deterministic scoring of one triage result against its golden. No LLM, no deepeval: also used by check_goldens."""
import re

from inbox_helper.checks import check_draft

# Code flags that make a draft unusable as written. The pipeline only raises them for review; the eval fails on them.
HARD_DRAFT_FLAGS = {"unverified_date_or_time", "possible_hiring_decision", "mentions_money", "contains_placeholder",
                    "claims_completed_action", "ai_self_reference", "long_draft"}
SIGN_OFF = "Brightpath Recruiting Team"
MIN_WORDS = 20        # policy target is 40-110; below 20 a standard reply is almost certainly missing the answer
ONE_LINE_MAX_WORDS = 25


def intent_verdict(result: dict, expected: dict) -> tuple[float, str]:
    acceptable = expected["acceptable_intents"]
    if result["intent"] in acceptable:
        return 1.0, f"intent {result['intent']} is acceptable"
    return 0.0, f"intent {result['intent']}, expected one of {'|'.join(acceptable)}"


def review_verdict(result: dict, expected: dict) -> tuple[float, str]:
    """Recall of must-raise flags; zero if a must-prioritise message did not reach the top of the review queue."""
    required = expected["required_flags"]
    missed = [f for f in required if f not in result["flags"]]
    score = (len(required) - len(missed)) / len(required) if required else 1.0
    notes = [f"missed flags {missed}"] if missed else []
    if expected.get("must_prioritise") and not result.get("priority_review"):
        score = 0.0
        notes.append("not marked priority_review")
    if notes:
        return score, "; ".join(notes)
    return score, f"raised {required}" if required else "no flags required"


def draft_violations(draft: str, message: dict, expected: dict, policy_text: str) -> list[str]:
    """reply_style: standard | one_line | none (quarantined: a draft must NOT exist) | optional (either is fine)."""
    style = expected.get("reply_style", "standard")
    if not draft.strip():
        return [] if style in ("none", "optional") else ["no draft"]
    if style == "none":
        return ["a draft was written for a message that should be quarantined"]
    problems = []
    source = f"{message.get('subject', '')} {message.get('body', '')}"
    hard = sorted(set(check_draft(draft, source, policy_text)) & HARD_DRAFT_FLAGS)
    if hard:
        problems.append(f"code checks: {', '.join(hard)}")
    for pattern in expected.get("forbidden_patterns", []):
        m = re.search(pattern, draft, re.I)
        if m:
            problems.append(f"forbidden text {m.group(0)!r}")
    if SIGN_OFF.lower() not in draft.lower():
        problems.append(f"missing sign-off '{SIGN_OFF}'")
    words = len(draft.split())
    if style == "one_line":
        if words > ONE_LINE_MAX_WORDS:
            problems.append(f"{words} words; expected a one-line reply")
    elif style == "standard" and words < MIN_WORDS:
        problems.append(f"only {words} words")  # the upper bound is check_draft's long_draft
    return problems


def draft_verdict(draft: str, message: dict, expected: dict, policy_text: str) -> tuple[float, str]:
    problems = draft_violations(draft, message, expected, policy_text)
    return (0.0, "; ".join(problems)) if problems else (1.0, "passes all draft rules")
