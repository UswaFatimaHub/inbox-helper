# Evals (deepeval + golden dataset)

Scores the inbox helper's output against a hand-written golden dataset. Everything lives in `evals/`; nothing in
the app is changed or imported in a way that writes to it.

## Setup (once)

deepeval has a large dependency tree, so it gets its own venv instead of the app's `.venv`:

```powershell
C:\Python312\python -m venv evals\.venv
evals\.venv\Scripts\python -m pip install -r evals\requirements.txt
```

The judge uses the same `.env` keys as the app (`GEMINI_API_KEY`, optionally `OPENROUTER_API_KEY`).

## Run (from the project root)

```powershell
# 1. Check the dataset itself: no network, no deepeval (also works with .venv\Scripts\python)
evals\.venv\Scripts\python -m evals.check_goldens

# 2. Score an existing run.py output with the deterministic metrics only: free, about 1 second
evals\.venv\Scripts\python -m evals.run_eval --results out\results.json --judge none

# 3. Add the LLM-judged metrics (about 6 judge calls per case with a draft)
evals\.venv\Scripts\python -m evals.run_eval --results out\results.json

# 4. Run the real pipeline on all goldens, including the holdout messages, then score it
evals\.venv\Scripts\python -m evals.run_eval --live
```

Useful flags: `--split sample|holdout`, `--ids M001,M027`, `--judge gemini|gemini-newest|none`,
`--metrics faithfulness,policy,quality`, `--profile standard|best` (for `--live`), `--fresh` (no cache).

## Eval gate (CI)

`run_eval` exits 1 whenever any case fails, and a few known misses always fail. CI therefore gates on a
comparison with the committed baseline, not on that exit code:

```powershell
evals\.venv\Scripts\python -m evals.run_eval --live --judge none   # rule metrics on all 64 goldens
evals\.venv\Scripts\python -m evals.gate                           # compare the newest run with evals/baseline.json
evals\.venv\Scripts\python -m evals.gate --update                  # accept it as the new baseline, then commit
```

- **What is gated.** The three rule metrics (Intent, Review routing, Draft rules). The LLM-judged metrics are too
  noisy to block a merge, and they cost about 6 calls per case. A manual CI run with the `judge` input reports
  them without gating.
- **When it fails.** A metric's passing count drops more than `tolerance` (2) below the baseline. The report
  lists newly failing and newly passing golden ids. A golden with no result counts as a failure.
- **Why there is a tolerance.** Regenerated drafts are not deterministic. In the first CI run (same prompt as
  the baseline, regenerated on an empty cache), each metric moved by about one case:

  | Metric | Baseline | CI run | Newly failing | Newly passing |
  |---|---|---|---|---|
  | Intent | 62/63 | 62/63 | - | - |
  | Review routing | 62/63 | 62/63 | G111 (missed `sensitive`) | M029 |
  | Draft rules | 61/63 | 60/63 | G110 (no sign-off) | - |

  A tolerance of 1 would have failed a change that made no difference, so it stays at 2. Revisit it after more
  runs. The `sensitive` flag and the sign-off are the least stable rules.

  **Correction (2026-10-30).** G111 was not noise. It missed `sensitive` in every later CI run (4 of 4). The flag's
  definition did not mention passwords, and the password itself reached the AI. Passwords are now hidden by
  `redact.py`, which also sets `sensitive` in code.
- **Must-pass cases.** The tolerance hid a real failure: G110, the boundary case added with prompt v4, failed on
  every CI run from that commit on, and the gate stayed green because one case is within the tolerance. So
  `baseline.json` now also lists `must_pass` cases, each with the metrics it must pass. Any one of them failing
  fails the gate. They are the manipulation attempts (M027, M043, M044, M047, G104), the look-alike that must not be
  quarantined (M046), hidden personal data (M039, G111), and people waiting for an answer who are not candidates
  (G110 and its sample twin M049). The manipulation cases and M046 never failed in 10 earlier runs; M039 and G111
  are decided by code; G110 and M049 were labelled correctly in all 3 prompt v8 runs.
- **Baseline.** Recorded 2026-10-30 from the first green CI run of prompt v8
  ([41094038734](https://github.com/UswaFatimaHub/inbox-helper/actions/runs/41094038734)), standard profile:
  - Intent: 63/64 (miss: M031)
  - Review routing: 63/64 (miss: M034, `unsupported_request` not flagged)
  - Draft rules: 61/64 (misses: M021 and M029 claimed an action; M049's one-line reply came out at 38 words)
  - Previous baseline (2026-10-27, prompt v3, 63 goldens, recorded locally): 62/63, 62/63, 61/63.
  - From now on, refresh the baseline from a CI run (`--update --scores <its scores.json>`), not from a local run.
- **Prompt changes cost API calls.** Each cached output is keyed on the exact prompt the model saw: the system
  prompt (instructions, intents, flags, policy) plus the rendered message. Any edit to these misses the cache,
  even if `PROMPT_VERSION` is not bumped. On top of that, CI keys its cache on the contents of `prompt.py`,
  `config.py`, `pipeline.py`, `providers.py`, the policy and the goldens. That also covers model and provider
  changes, which the prompt text does not show. Changing any of these files regenerates every output: about 12
  batches of 5, plus retries.

Each run writes `evals/runs/<timestamp>-<source>/`: `report.md` (pass rates per metric and split, plus every
failure with its reason), `scores.json`, deepeval's own test-run JSON under `deepeval/` and, for `--live`, the
`results.json` it scored. The exit code is 1 if any metric failed.

## The golden dataset: `goldens.json`

64 goldens:
- **48 `sample`** mirror `data/messages.csv` exactly. M041 is left out because the loader rejects its empty body
  before any model sees it.
- **16 `holdout`** (G101–G116) are new messages that are not in the sample inbox. Use them to check that a
  prompt change generalises rather than fitting the sample.

Each golden has:

| Field | Used by |
|---|---|
| `acceptable_intents` | Intent metric (any one counts) |
| `required_flags`, `must_prioritise` | Review routing metric |
| `reply_style`: `standard`, `one_line`, `none` (quarantined, so a draft must not exist) or `optional` | Draft rules metric |
| `forbidden_patterns` (regex, case-insensitive) | Draft rules metric, for clear-cut leaks such as a repeated CNIC or password |
| `must` / `must_not` | Policy compliance judge (passed as `context`) |
| `policy_refs` → `policy_excerpts` | Policy compliance judge. Each excerpt must appear verbatim in the policy. |
| `reference_reply` | Reply quality judge (passed as `expected_output`). Must itself pass the draft rules. |

`check_goldens` fails if an excerpt is not verbatim in the policy, a sample golden drifts from `messages.csv`, a
valid sample message has no golden, or a reference reply breaks the app's own rules. It warns where the goldens
and `data/expected_labels.csv` disagree. **When the dataset generator or the taxonomy changes, run it first.**

## Metrics

| Metric | Kind | Passes when |
|---|---|---|
| Intent | rule | intent is in `acceptable_intents` |
| Review routing | rule | every required flag is present, and `priority_review` is set where `must_prioritise` |
| Draft rules | rule | no hard code-check flag from `inbox_helper.checks.check_draft` (invented date/time, decision, money, placeholder, claimed action, "I"/AI voice, too long), no forbidden text, signed "Brightpath Recruiting Team", sensible length, and no draft at all for quarantined messages |
| Faithfulness | deepeval `FaithfulnessMetric` ≥ 0.8 | every claim in the draft is supported by the policy sections or the candidate's message |
| Policy compliance | deepeval `GEval` ≥ 0.7 | every MUST is met and no MUST NOT is violated |
| Reply quality | deepeval `GEval` ≥ 0.6 | addresses every ask at least as well as the reference, with the right tone, language and length |

Judge metrics only run on cases that have a draft. If a message needed a reply and got none (for example
`processing_failed`, or a false-positive quarantine), every judge metric counts it as a failure.

## Caveats

- **Shared quota.** The judge uses the same Gemini key as the app. While the app is running, `gemini-3.5-flash`
  often returns 429 and the judge falls back to `gemini-3.5-flash-lite`, which is a weaker judge. The report's
  `Judge:` line says which models actually judged. Prefer running judged evals while the app is idle. The default
  judge avoids OpenRouter because its free tier allows only 50 requests a day.
- **Self-preference.** The default judge is the same model family that writes the drafts.
  `--judge gemini-newest` uses a newer model when one is available.
- LLM-judge scores are noisy. Treat a single judge failure as a prompt to read the draft, not as a verdict. The
  rule metrics are exact.
- The goldens were written with AI help and should be reviewed by a recruiter, like `data/expected_labels.csv`.
  The `must`/`must_not` lists are the part most worth checking.
