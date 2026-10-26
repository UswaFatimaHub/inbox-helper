"""Score the inbox helper against evals/goldens.json with deepeval.

Run from the project root with the eval venv:
  evals\\.venv\\Scripts\\python -m evals.run_eval --results out\\results.json --judge none   # rules only, free
  evals\\.venv\\Scripts\\python -m evals.run_eval --results out\\results.json                # + LLM judge
  evals\\.venv\\Scripts\\python -m evals.run_eval --live                                     # run the app on the goldens

Writes evals/runs/<timestamp>-<source>/ with report.md, scores.json and deepeval's own test-run file.
Nothing outside evals/ is written: --live reads the app's .cache read-only and caches into evals/.cache.
"""
import argparse
import json
import sys
import time
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from deepeval import evaluate
from deepeval.evaluate.configs import AsyncConfig, CacheConfig, DisplayConfig, ErrorConfig
from deepeval.test_case import LLMTestCase

from inbox_helper.config import CACHE_PATH, DEFAULT_POLICY, DEFAULT_PROFILE, PROFILES, PROMPT_VERSION, load_api_keys
from inbox_helper.loader import load_messages
from inbox_helper.pipeline import Cache, TriageRun, build_lanes

from .goldens import EVAL_DIR, ROOT, GoldenCase, as_input_records, checklist, load_goldens, policy_sections, \
    render_message
from .judge import JUDGE_PROFILES, build_judge
from .metrics import JUDGE_METRIC_NAMES, judge_metrics, rule_metrics

RUNS_DIR = EVAL_DIR / "runs"
EVAL_CACHE = EVAL_DIR / ".cache" / "triage_cache.json"
RESULT_FIELDS = ("intent", "secondary_intent", "confidence", "flags", "priority_review", "draft_reply", "lane",
                 "model", "prompt_version", "error")


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--results", type=Path, help="score an existing results.json written by run.py (no generation)")
    src.add_argument("--live", action="store_true", help="run the triage pipeline on the golden messages (uses quota)")
    p.add_argument("--profile", default=DEFAULT_PROFILE, choices=sorted(PROFILES), help="model profile for --live")
    p.add_argument("--fresh", action="store_true", help="--live without any cache")
    p.add_argument("--judge", default="gemini", choices=[*JUDGE_PROFILES, "none"],
                   help="judge model lanes; 'none' runs only the deterministic metrics")
    p.add_argument("--metrics", default=",".join(JUDGE_METRIC_NAMES),
                   help=f"judge metrics to run (comma-separated from {', '.join(JUDGE_METRIC_NAMES)})")
    p.add_argument("--split", default="all", choices=["all", "sample", "holdout"])
    p.add_argument("--ids", help="only these golden ids, e.g. M001,M027,G104")
    p.add_argument("--concurrency", type=int, default=2, help="judge test cases evaluated in parallel")
    args = p.parse_args(argv)
    args.metrics = [m.strip() for m in args.metrics.split(",") if m.strip()]
    unknown = set(args.metrics) - set(JUDGE_METRIC_NAMES)
    if unknown:
        p.error(f"unknown --metrics {sorted(unknown)}")
    return args


def select(cases: list[GoldenCase], args) -> list[GoldenCase]:
    if args.split != "all":
        cases = [c for c in cases if c.split == args.split]
    if args.ids:
        wanted = {i.strip() for i in args.ids.split(",")}
        missing = wanted - {c.id for c in cases}
        if missing:
            sys.exit(f"unknown golden id(s) for this split: {sorted(missing)}")
        cases = [c for c in cases if c.id in wanted]
    return cases


# ---- sources of app output ---------------------------------------------------------------------------------
def results_from_file(path: Path, cases: list[GoldenCase]) -> tuple[dict[str, dict], dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data["results"] if isinstance(data, dict) else data
    by_id = {r["message_id"]: r for r in rows}
    found = {}
    for c in cases:
        r = by_id.get(c.id)
        if r is None:
            continue
        if " ".join(r.get("body", "").split()) != " ".join(c.message["body"].split()):
            print(f"warning: {c.id} in {path.name} is a different message than the golden; not scored")
            continue
        found[c.id] = r
    info = data.get("run", {}) if isinstance(data, dict) else {}
    return found, {"source": str(path), **info}


def results_from_live_run(cases: list[GoldenCase], profile: str, fresh: bool, policy: str,
                          run_dir: Path) -> tuple[dict[str, dict], dict]:
    inputs = run_dir / "inputs.json"
    inputs.write_text(json.dumps(as_input_records(cases), ensure_ascii=False, indent=1), encoding="utf-8")
    loaded = load_messages(inputs)  # the real loader, so loader warnings (invalid_email, duplicates) apply
    for err in loaded.errors:
        print(f"input error on {err.message_id or err.row}: {err.error}")
    lanes = build_lanes(PROFILES[profile], load_api_keys(), print)
    if not lanes:
        sys.exit("No usable provider lanes: add GEMINI_API_KEY and/or OPENROUTER_API_KEY to .env.")
    cache = Cache(None if fresh else EVAL_CACHE)
    if not fresh and CACHE_PATH.exists():  # reuse the app's cached outputs read-only; new ones go to evals/.cache
        try:
            for key, value in json.loads(CACHE_PATH.read_text(encoding="utf-8")).items():
                if cache.get(key) is None:
                    cache.put(key, value)
        except (ValueError, OSError):
            pass
    started = time.monotonic()
    results = TriageRun(lanes, policy, cache=cache, batch_size=5, log=print).run(loaded.messages)
    rows = [asdict(r) for r in results]
    info = {"source": "live", "profile": profile, "prompt_version": PROMPT_VERSION,
            "elapsed_s": round(time.monotonic() - started, 1),
            "lanes": [{"name": l.name, "calls": l.calls, "failures": l.failures, "disabled": l.disabled}
                      for l in lanes]}
    (run_dir / "results.json").write_text(json.dumps({"run": info, "results": rows}, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    return {r["message_id"]: r for r in rows}, info


# ---- deepeval ----------------------------------------------------------------------------------------------
def to_test_case(case: GoldenCase, result: dict, sections: list[str]) -> LLMTestCase:
    message = render_message(case)
    return LLMTestCase(
        name=case.id, input=message, actual_output=result.get("draft_reply") or "",
        expected_output=case.reference_reply or None, context=checklist(case),
        retrieval_context=sections + [f"Candidate message:\n{message}"],
        metadata={"expected": case.expected, "message": case.message,
                  "result": {k: result.get(k) for k in RESULT_FIELDS}},
        tags=[case.split, case.category, case.difficulty])


def run_deepeval(test_cases, metrics, run_dir: Path, concurrency: int, label: str, hyperparameters: dict):
    if not test_cases or not metrics:
        return []
    print(f"\ndeepeval: {label} ({len(test_cases)} case(s) x {len(metrics)} metric(s))")
    result = evaluate(
        test_cases=test_cases, metrics=metrics, identifier=label, hyperparameters=hyperparameters,
        async_config=AsyncConfig(run_async=True, max_concurrent=concurrency),
        display_config=DisplayConfig(print_results=False, show_indicator=True,
                                     results_folder=str(run_dir / "deepeval")),
        error_config=ErrorConfig(ignore_errors=True, skip_on_missing_params=True),
        cache_config=CacheConfig(write_cache=False, use_cache=False))
    rows = []
    for tr in result.test_results:
        for md in tr.metrics_data or []:
            rows.append({"id": tr.name, "metric": md.name, "score": md.score, "success": bool(md.success),
                         "reason": md.error or md.reason, "error": bool(md.error)})
    return rows


# ---- report ------------------------------------------------------------------------------------------------
def summarise(rows: list[dict], cases: list[GoldenCase], not_run: list[str], info: dict, judge_info: str) -> str:
    split_of = {c.id: c.split for c in cases}
    table = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # metric -> split -> [passed, total]
    for r in rows:
        for split in ("all", split_of[r["id"]]):
            table[r["metric"]][split][0] += r["success"]
            table[r["metric"]][split][1] += 1

    def cell(passed_total):
        passed, total = passed_total
        return f"{passed}/{total} ({passed / total:.0%})" if total else "-"

    lines = [f"# Eval report ({datetime.now():%Y-%m-%d %H:%M})", "",
             f"- Source: {info.get('source')}  | prompt {info.get('prompt_version', '?')}"
             f"  | profile {info.get('profile', '?')}",
             f"- Goldens: {len(cases)} selected, {len(cases) - len(not_run)} scored"
             + (f", {len(not_run)} with no result: {', '.join(not_run)}" if not_run else ""),
             f"- Judge: {judge_info}", "",
             "| Metric | All | Sample | Holdout |", "|---|---|---|---|"]
    for metric, splits in table.items():
        lines.append(f"| {metric} | {cell(splits['all'])} | {cell(splits['sample'])} | {cell(splits['holdout'])} |")
    failures = [r for r in rows if not r["success"]]
    lines += ["", f"## Failures ({len(failures)})", ""]
    for r in sorted(failures, key=lambda r: (r["id"], r["metric"])):
        score = "error" if r["error"] else f"{r['score']:.2f}" if r["score"] is not None else "-"
        reason = " ".join(str(r["reason"] or "").split())
        lines.append(f"- **{r['id']}** {r['metric']} ({score}): {reason[:400]}")
    return "\n".join(lines)


def main(argv=None) -> int:
    args = parse_args(argv)
    _, cases = load_goldens()
    cases = select(cases, args)
    policy = DEFAULT_POLICY.read_text(encoding="utf-8")
    source = "live" if args.live else args.results.stem
    run_dir = RUNS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-{source}"
    run_dir.mkdir(parents=True)

    if args.live:
        results, info = results_from_live_run(cases, args.profile, args.fresh, policy, run_dir)
    else:
        path = args.results if args.results.is_absolute() else ROOT / args.results
        if not path.exists():
            sys.exit(f"results file not found: {path}")
        results, info = results_from_file(path, cases)
    not_run = [c.id for c in cases if c.id not in results]
    scored = [c for c in cases if c.id in results]
    sections = policy_sections(policy)
    test_cases = {c.id: to_test_case(c, results[c.id], sections) for c in scored}
    hyper = {"prompt_version": str(info.get("prompt_version", "?")), "profile": str(info.get("profile", "?"))}

    rows = run_deepeval(list(test_cases.values()), rule_metrics(policy), run_dir, 20, "rules", hyper)

    judge_info = "none (deterministic metrics only)"
    if args.judge != "none" and args.metrics:
        judge = build_judge(args.judge, load_api_keys())
        if judge is None:
            judge_info = f"skipped: no API key for the '{args.judge}' judge lanes"
        else:
            # Judge only real drafts. A missing draft where one was expected fails every judge metric outright.
            with_draft = [c for c in scored if test_cases[c.id].actual_output.strip()]
            judged = run_deepeval([test_cases[c.id] for c in with_draft], judge_metrics(judge, args.metrics),
                                  run_dir, args.concurrency, f"judge-{args.judge}", hyper)
            rows += judged
            metric_names = sorted({r["metric"] for r in judged})
            for c in scored:
                if not test_cases[c.id].actual_output.strip() and c.expected.get("reply_style") in ("standard", "one_line"):
                    rows += [{"id": c.id, "metric": m, "score": 0.0, "success": False,
                              "reason": "no draft to judge, but this message needs a reply", "error": False}
                             for m in metric_names]
            used = ", ".join(f"{m} x{n}" for m, n in judge.models_used.most_common()) or "no successful calls"
            judge_info = f"{args.judge}: {used}; {judge.failures} failed call(s)"

    report = summarise(rows, cases, not_run, info, judge_info)
    (run_dir / "report.md").write_text(report + "\n", encoding="utf-8")
    (run_dir / "scores.json").write_text(json.dumps({"run": info, "judge": judge_info, "not_run": not_run,
                                                     "scores": rows}, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    print("\n" + report)
    print(f"\nWrote {run_dir}")
    return 0 if rows and all(r["success"] for r in rows) else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    sys.exit(main())
