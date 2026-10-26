"""Integrity checks for evals/goldens.json. No network, no deepeval: runs in the app's .venv too.

Run: python -m evals.check_goldens
Errors (exit 1): the dataset is wrong. Warnings: the goldens and data/expected_labels.csv disagree, which may be
deliberate (goldens can be stricter) but should be a conscious choice.
"""
import csv
import re
import sys

from inbox_helper.config import ALL_INTENTS, CODE_FLAGS, DEFAULT_POLICY, FLAGS
from inbox_helper.loader import load_messages

from .goldens import MESSAGE_FIELDS, ROOT, load_goldens
from .rules import draft_violations

SAMPLE_INPUT = ROOT / "data" / "messages.csv"
SAMPLE_LABELS = ROOT / "data" / "expected_labels.csv"
SPLITS = {"sample", "holdout"}
REPLY_STYLES = {"standard", "one_line", "none", "optional"}


def _norm(text: str) -> str:
    return " ".join(text.split())


def check() -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    policy = DEFAULT_POLICY.read_text(encoding="utf-8")
    try:
        data, cases = load_goldens()
    except (ValueError, KeyError) as e:
        return [f"goldens.json cannot be loaded: {e}"], []

    norm_policy = _norm(policy)
    for key, text in data["policy_excerpts"].items():
        if _norm(text) not in norm_policy:
            errors.append(f"policy excerpt '{key}' is not verbatim in {DEFAULT_POLICY.name}")
    used = {r for c in cases for r in c.policy_refs}
    for key in sorted(set(data["policy_excerpts"]) - used):
        warnings.append(f"policy excerpt '{key}' is not used by any golden")

    seen = set()
    for c in cases:
        e = c.expected
        where = f"{c.id}:"
        if c.id in seen:
            errors.append(f"{where} duplicate id")
        seen.add(c.id)
        if c.split not in SPLITS:
            errors.append(f"{where} split '{c.split}' not in {sorted(SPLITS)}")
        if not e["acceptable_intents"] or set(e["acceptable_intents"]) - ALL_INTENTS.keys():
            errors.append(f"{where} bad acceptable_intents {e['acceptable_intents']}")
        if set(e["required_flags"]) - FLAGS.keys() - CODE_FLAGS.keys():
            errors.append(f"{where} unknown required_flags {set(e['required_flags']) - FLAGS.keys() - CODE_FLAGS.keys()}")
        if e.get("reply_style", "standard") not in REPLY_STYLES:
            errors.append(f"{where} reply_style must be one of {sorted(REPLY_STYLES)}")
        if not e["must"] or not isinstance(e["must_not"], list):
            errors.append(f"{where} needs at least one 'must' item and a 'must_not' list")
        for p in e.get("forbidden_patterns", []):
            try:
                re.compile(p)
            except re.error as err:
                errors.append(f"{where} forbidden pattern {p!r} does not compile: {err}")
        if not c.message["body"].strip():
            errors.append(f"{where} empty body (the loader would reject it)")
        style = e.get("reply_style", "standard")
        if (style == "none") != (not c.reference_reply.strip()):
            errors.append(f"{where} reference_reply must be empty exactly when reply_style is 'none'")
        # The reference reply is the bar for the app, so it has to pass the app's own rules.
        for problem in draft_violations(c.reference_reply, c.message, e, policy):
            errors.append(f"{where} reference reply fails draft rules: {problem}")

    _check_against_sample(cases, errors, warnings)
    return errors, warnings


def _check_against_sample(cases, errors: list[str], warnings: list[str]) -> None:
    """Sample goldens must match data/messages.csv exactly, and cover every message the loader accepts."""
    loaded = load_messages(SAMPLE_INPUT)
    sample = {m.message_id: m for m in loaded.messages}
    goldens = {c.id: c for c in cases if c.split == "sample"}
    for mid in sorted(set(sample) - set(goldens)):
        errors.append(f"{mid}: in {SAMPLE_INPUT.name} but has no sample golden")
    for mid, c in goldens.items():
        m = sample.get(mid)
        if m is None:
            errors.append(f"{mid}: sample golden has no valid row in {SAMPLE_INPUT.name}")
            continue
        diff = [f for f in MESSAGE_FIELDS if getattr(m, f) != c.message[f]]
        if diff:
            errors.append(f"{mid}: golden message differs from {SAMPLE_INPUT.name} in {diff}")
    for c in cases:
        if c.split == "holdout" and c.id in sample:
            errors.append(f"{c.id}: holdout id collides with a sample message")

    with open(SAMPLE_LABELS, encoding="utf-8-sig", newline="") as f:
        labels = {row["message_id"]: row for row in csv.DictReader(f)}
    for mid, c in goldens.items():
        lab = labels.get(mid)
        if lab is None:
            warnings.append(f"{mid}: no row in {SAMPLE_LABELS.name}")
            continue
        lab_intents = {i for i in lab["acceptable_intents"].split("|") if i}
        if lab_intents != set(c.expected["acceptable_intents"]):
            warnings.append(f"{mid}: acceptable intents {sorted(c.expected['acceptable_intents'])} "
                            f"vs labels {sorted(lab_intents)}")
        lab_flags = {x for x in lab["expected_flags"].split("|") if x}
        if not lab_flags <= set(c.expected["required_flags"]):
            warnings.append(f"{mid}: labels expect flags {sorted(lab_flags)}, golden requires "
                            f"{sorted(c.expected['required_flags'])}")


def main() -> int:
    errors, warnings = check()
    _, cases = load_goldens()
    splits = {s: sum(c.split == s for c in cases) for s in sorted(SPLITS)}
    print(f"{len(cases)} goldens ({', '.join(f'{n} {s}' for s, n in splits.items())})")
    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"ERROR: {e}")
    print("OK" if not errors else f"{len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
