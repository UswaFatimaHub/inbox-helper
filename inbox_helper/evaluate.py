"""Score triage results against hand-written labels: intent accuracy and recall of must-raise flags."""
import csv
from pathlib import Path


def evaluate(results: list[dict], labels_path: Path) -> dict:
    by_id = {r["message_id"]: r for r in results}
    with open(labels_path, encoding="utf-8-sig", newline="") as f:
        labels = list(csv.DictReader(f))
    problems, intent_ok, flag_hits, flag_total = [], 0, 0, 0
    for lab in labels:
        r = by_id.get(lab["message_id"])
        if r is None:
            problems.append(f"{lab['message_id']}: no result")
            continue
        acceptable = [i for i in lab["acceptable_intents"].split("|") if i]
        expected_flags = [f for f in lab["expected_flags"].split("|") if f]
        ok = r["intent"] in acceptable
        intent_ok += ok
        missed = [f for f in expected_flags if f not in r["flags"]]
        flag_total += len(expected_flags)
        flag_hits += len(expected_flags) - len(missed)
        if not ok or missed:
            problems.append(f"{lab['message_id']}: got {r['intent']}, expected {'|'.join(acceptable)}"
                            + (f", missed flags {missed}" if missed else "")
                            + (f"  ({lab['note']})" if lab.get("note") else ""))
    return {"scored": len(labels), "intent_correct": intent_ok, "flags_expected": flag_total,
            "flags_hit": flag_hits, "problems": problems}


def format_report(rep: dict) -> str:
    acc = rep["intent_correct"] / rep["scored"] if rep["scored"] else 0.0
    recall = rep["flags_hit"] / rep["flags_expected"] if rep["flags_expected"] else 1.0
    lines = [f"Intent accuracy: {rep['intent_correct']}/{rep['scored']} = {acc:.0%}",
             f"Must-raise flag recall: {rep['flags_hit']}/{rep['flags_expected']} = {recall:.0%}"]
    if rep["problems"]:
        lines += ["Mismatches:"] + [f"  {p}" for p in rep["problems"]]
    return "\n".join(lines)
