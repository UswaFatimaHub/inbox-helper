"""Prototype runner: triage data/messages.csv and write results for human review.

Run: .venv\\Scripts\\python run.py
Nothing is sent anywhere; every draft is saved as 'pending' review.
"""
import csv
import json
import os
import sys
import time
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

from inbox_helper.config import (CACHE_PATH, DEFAULT_LANES, DEFAULT_POLICY, DEFAULT_PROFILE, INTENTS, PROMPT_VERSION,
                                 ROOT, load_api_keys)
from inbox_helper.evaluate import evaluate, format_report
from inbox_helper.loader import InputError, load_messages
from inbox_helper.pipeline import Cache, TriageRun, build_lanes

INPUT = ROOT / "data" / "messages.csv"
LABELS = ROOT / "data" / "expected_labels.csv"
OUT = ROOT / os.environ.get("OUT_DIR", "out")
BATCH_SIZE = 5
USE_CACHE = os.environ.get("USE_CACHE", "1") != "0"

REVIEW_COLUMNS = ["message_id", "priority_review", "intent", "secondary_intent", "confidence", "flags",
                  "candidate_name", "subject", "body", "draft_reply", "review_status", "final_reply", "reviewed_by"]


def main() -> int:
    try:
        loaded = load_messages(INPUT)
    except InputError as e:
        print(f"Input error: {e}")
        return 2
    for err in loaded.errors:
        print(f"Skipped row {err.row} ({err.message_id or 'no id'}): {err.error}")
    if not loaded.messages:
        print("Input error: no valid messages to process.")
        return 2

    policy = DEFAULT_POLICY.read_text(encoding="utf-8")
    lanes = build_lanes(DEFAULT_LANES, load_api_keys(), print)
    if not lanes:
        print("No usable provider lanes: add GEMINI_API_KEY and/or OPENROUTER_API_KEY to .env.")
        return 1

    started = time.monotonic()
    run = TriageRun(lanes, policy, cache=Cache(CACHE_PATH if USE_CACHE else None), batch_size=BATCH_SIZE, log=print)
    results = run.run(loaded.messages)
    elapsed = time.monotonic() - started

    OUT.mkdir(exist_ok=True)
    rows = [asdict(r) for r in results]
    record = {
        "run": {"input": str(INPUT), "prompt_version": PROMPT_VERSION, "profile": DEFAULT_PROFILE, "elapsed_s": round(elapsed, 1),
                "batch_size": BATCH_SIZE,
                "lanes": [{"name": l.name, "calls": l.calls, "failures": l.failures, "disabled": l.disabled}
                          for l in lanes]},
        "input_errors": [asdict(e) for e in loaded.errors],
        "results": rows,
    }
    (OUT / "results.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(OUT / "review.csv", "w", newline="", encoding="utf-8-sig") as f:  # BOM: Excel shows Urdu correctly
        w = csv.DictWriter(f, fieldnames=REVIEW_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for row in sorted(rows, key=lambda r: (not r["priority_review"], r["intent"], r["message_id"])):
            w.writerow({**row, "flags": "|".join(row["flags"])})

    print_summary(results, elapsed, lanes)
    if LABELS.exists():
        print("\n" + format_report(evaluate(rows, LABELS)))
    print(f"\nWrote {OUT / 'results.json'} (audit record) and {OUT / 'review.csv'} (review sheet).")
    print("Nothing has been sent. Every draft is 'pending' until a human reviews it.")
    return 0


def print_summary(results, elapsed: float, lanes) -> None:
    groups = defaultdict(list)
    for r in results:
        groups[r.intent].append(r)
    print(f"\nTriaged {len(results)} message(s) in {elapsed:.1f}s")
    print("Lanes: " + ", ".join(f"{l.name} {l.calls} call(s)/{l.failures} failed"
                                + (" [disabled]" if l.disabled else "") for l in lanes))
    for intent in INTENTS:
        for i, r in enumerate(groups.get(intent, [])):
            if i == 0:
                print(f"\n== {intent} ({len(groups[intent])}) ==")
            mark = "!" if r.priority_review else " "
            flags = f"  [{', '.join(r.flags)}]" if r.flags else ""
            preview = r.draft_reply.replace("\n", " ")[:90] or f"(no draft: {r.error})"
            print(f" {mark} {r.message_id} {r.candidate_name[:18]:<18} {r.confidence:.2f}  {preview}{flags}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)  # Windows console: Urdu/Spanish text
    sys.exit(main())
