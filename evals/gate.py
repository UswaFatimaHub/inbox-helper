"""Eval gate: fail when a prompt, model or pipeline change scores worse than the committed baseline.

  python -m evals.gate                       # compare the newest evals/runs/*/scores.json with evals/baseline.json
  python -m evals.gate --scores <path>       # a specific run
  python -m evals.gate --update              # accept the newest run as the new baseline (commit the file)

run_eval exits 1 whenever any case fails, and some known misses always fail, so CI gates on this instead: per
metric, the number of passing goldens may not drop more than `tolerance` below the baseline. Live generation is not
deterministic, so the tolerance absorbs a case flipping between runs; a real regression shows up as several
newly failing cases, which the report lists by id. A golden with no result counts as failed.

The tolerance can also hide one important case failing on every run (G110 did, from prompt v4 to v6, and nobody read
the report). So the baseline also lists `must_pass` cases (safety and boundary cases, each with the metrics it must
pass), and any one of them failing fails the gate whatever the tolerance.

Raising the baseline is part of the change that earns it: run with --update and commit evals/baseline.json, so the
reviewer sees the new numbers next to the prompt diff.
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
BASELINE = EVAL_DIR / "baseline.json"
RUNS_DIR = EVAL_DIR / "runs"
DEFAULT_TOLERANCE = 2  # passing cases a metric may lose; a guess until a few CI runs show the real run-to-run noise


def latest_scores() -> Path:
    runs = sorted(RUNS_DIR.glob("*/scores.json"))
    if not runs:
        sys.exit("no eval runs found under evals/runs; run evals.run_eval first")
    return runs[-1]


def summarise(scores: dict) -> dict[str, dict]:
    """metric -> {passed, total, failing ids}. Goldens with no result count as failing every metric."""
    by_metric: dict[str, dict[str, bool]] = {}
    for row in scores["scores"]:
        by_metric.setdefault(row["metric"], {})[row["id"]] = bool(row["success"])
    out = {}
    for metric, results in by_metric.items():
        failing = sorted({i for i, ok in results.items() if not ok} | set(scores.get("not_run", [])))
        total = len(set(results) | set(scores.get("not_run", [])))
        out[metric] = {"passed": total - len(failing), "total": total, "failing": failing}
    return out


def compare(baseline: dict, current: dict[str, dict]) -> tuple[bool, list[str]]:
    tolerance = baseline.get("tolerance", DEFAULT_TOLERANCE)
    ok = True
    lines = ["| Metric | Baseline | This change | Newly failing | Newly passing |", "|---|---|---|---|---|"]
    for metric, base in baseline["metrics"].items():
        cur = current.get(metric)
        if cur is None:
            ok = False
            lines.append(f"| {metric} | {base['passed']}/{base['total']} | **not measured** | | |")
            continue
        worse = sorted(set(cur["failing"]) - set(base["failing"]))
        better = sorted(set(base["failing"]) - set(cur["failing"]))
        failed = cur["passed"] < base["passed"] - tolerance
        ok &= not failed
        mark = " ❌" if failed else ""
        lines.append(f"| {metric} | {base['passed']}/{base['total']} | {cur['passed']}/{cur['total']}{mark} | "
                     f"{', '.join(worse) or '-'} | {', '.join(better) or '-'} |")
    dropped = not ok
    must_pass = baseline.get("must_pass", {})
    missed = [f"{case} ({metric})" for case, metrics in must_pass.items() for metric in metrics
              if case in current.get(metric, {}).get("failing", [case])]
    ok &= not missed
    lines += ["", f"Must-pass cases ({len(must_pass)}): " + (f"**failed: {', '.join(missed)}**" if missed else "all passed")]
    reasons = [r for r, bad in (("a metric dropped more than the tolerance", dropped),
                                ("a must-pass case failed", bool(missed))) if bad]
    verdict = "**Eval gate passed**" if ok else "**Eval gate failed**: " + "; ".join(reasons)
    return ok, [verdict + f" (tolerance: {tolerance} case(s) per metric)", ""] + lines


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--scores", type=Path, help="scores.json of the run to check (default: newest run)")
    p.add_argument("--update", action="store_true", help="write this run as the new baseline")
    p.add_argument("--metrics", help="metrics to record with --update (default: those already in the baseline, "
                                     "or every metric in the run)")
    args = p.parse_args(argv)
    path = args.scores or latest_scores()
    scores = json.loads(path.read_text(encoding="utf-8"))
    current = summarise(scores)

    if args.update:
        old = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
        names = ([m.strip() for m in args.metrics.split(",")] if args.metrics
                 else list(old.get("metrics", {})) or list(current))
        missing = [m for m in names if m not in current]
        if missing:
            sys.exit(f"metrics not in this run: {missing}")
        run = scores.get("run", {})
        BASELINE.write_text(json.dumps({
            "about": "Eval gate baseline (python -m evals.gate). Update with --update and commit with the change.",
            "recorded": f"{datetime.now():%Y-%m-%d}", "source": run.get("source"),
            "prompt_version": run.get("prompt_version"), "profile": run.get("profile"),
            "tolerance": old.get("tolerance", DEFAULT_TOLERANCE), "must_pass": old.get("must_pass", {}),
            "metrics": {m: current[m] for m in names}}, indent=2) + "\n", encoding="utf-8")
        print(f"Baseline updated from {path}")
        return 0

    if not BASELINE.exists():
        sys.exit("evals/baseline.json is missing; create it with --update")
    ok, lines = compare(json.loads(BASELINE.read_text(encoding="utf-8")), current)
    report = "\n".join([f"## Eval gate", "", f"Run: `{path.parent.name}`", ""] + lines)
    print(report)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as f:
            f.write(report + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
