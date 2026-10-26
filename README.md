# Inbox Helper

Takes a pile of candidate messages, groups them by what the person wants, and drafts a short reply for each.
**Nothing is sent.** A person approves, edits or rejects every draft, and every action is recorded in an audit
trail. Approved replies can only be copied or exported.

## Setup

Requires Python 3.12, Node 22 and a `.env` file in the project root (either key alone works):

```
GEMINI_API_KEY=...
OPENROUTER_API_KEY=...
```

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
cd frontend; npm install; npm run build; cd ..
```

## Run the app

```powershell
.venv\Scripts\python -m uvicorn inbox_helper.server:app --port 8000
```

Open http://127.0.0.1:8000, enter your name at the top, then click **New triage** and either upload a CSV or JSON
file or use the sample inbox. Drafts appear as the AI finishes them. Review the **Needs attention** group first.
Keyboard: `J`/`K` move between messages, `Ctrl+Enter` approves.

For frontend development with hot reload, also run `cd frontend; npm run dev` and open http://localhost:5173. It
forwards `/api` requests to the server on port 8000.

Data is stored in SQLite at `.data/inbox.db`. To use Postgres, set
`DATABASE_URL=postgresql+psycopg://user:pass@host/db` and install `psycopg`.

## Other entry points

```powershell
.venv\Scripts\python run.py                        # batch run without the UI: writes out/results.json + out/review.csv
.venv\Scripts\python scripts\generate_dataset.py   # re-create the synthetic dataset and expected labels
.venv\Scripts\python -m pytest                      # tests (fake model clients, in-memory DB, no API quota used)
```

`MODEL_PROFILE=best` switches to the strongest free models. It was measured as slower with no quality gain; see
"Model choice" below.

## How it works

```
CSV/JSON -> loader (validation, row errors) -> batches of 5 -> shared queue
   -> lanes: openrouter | gemini-3.5-flash | gemini-3.5-flash-lite   (each with its own rate limiter)
   -> parse JSON -> validate labels -> code checks on the draft -> one item per message (DB) -> human review
```

- **One request classifies and drafts five messages.** OpenRouter's free tier allows 50 requests a day; the
  41-message sample uses about 9.
- **Lanes.** Gemini quotas are counted per model, so each model is a separate lane. All lanes pull from one
  queue, so the fastest healthy lane does most of the work.
- **Failure handling.** A failed batch moves to another lane. An unparseable batch is split into single
  messages, each with a fresh retry budget. If every lane fails, the message still appears, flagged
  `processing_failed`, for a manual reply.
- **The model is not trusted.** Intent labels are checked against the allowed set. Code then scans each draft
  for:
  - dates or times that appear in neither the message nor the policy
  - wording that implies a hiring decision
  - money amounts and `[placeholders]`
  - claims that an action was already done ("has been recorded")
  - the AI speaking as "I"
- **Policy.** `policies/recruiting_policy.md` (for a fictional company) is the only source of facts the drafts
  may use.

## Manipulation attempts and the blocklist

Messages that try to instruct the AI ("ignore all previous instructions…", fake `[SYSTEM]` notes, "AI assistant:
disregard your rules…") are **quarantined**. They get the category `manipulation_attempt` and no reply is drafted.

- **Two layers of detection.**
  1. Narrow patterns in plain code (`checks.detect_injection`) catch known phrases *before* any AI call, so that
     text never reaches the model.
  2. If the model itself flags `prompt_injection` (for example in another language), its draft is thrown away.
- **No over-blocking.** The patterns are deliberately narrow. "Please ignore my previous email" is a normal message,
  and a test checks that.
- **Blocking is one click, not automatic.** **Block sender** adds the email address to the blocklist and closes
  every pending message from that sender, in every run. From then on their messages are labelled `blocked_sender`:
  never sent to the AI, never answered, but still recorded for the audit trail.
- **Why a person decides.** A wrong detection or a forged "From" address would otherwise permanently shut out a
  real candidate.
- **Undoing it.** **Manage blocklist** in the sidebar unblocks a sender, and any blocked message can be reopened.

## Model choice (measured, 41 messages)

| Prompt | Models | Time | Intents correct | No draft | Bad drafts* |
|---|---|---|---|---|---|
| v1 | standard (3.5 Flash/Flash-Lite, Nemotron Super) | 125 s | 40/41 | 0 | 12 |
| v2 | best free (3.8→3.6 Flash, Nemotron Ultra 550B) | 415 s | 37/41 | 3 | 2 |
| v2 | standard | 120 s | 40/41 | 0 | 0 |

\*Drafts that claimed an action was done or spoke as the AI.

The prompt fixed the drafts; the bigger models didn't help. Gemini Pro models have no free quota on this key.

## Layout

| Path | What |
|---|---|
| `inbox_helper/api.py`, `server.py` | FastAPI: runs, items, review actions, export, audit |
| `inbox_helper/db.py` | SQLAlchemy models: runs, items, review_events |
| `inbox_helper/pipeline.py` | Lane scheduler, retries, cache, result records |
| `inbox_helper/checks.py` | Output parsing, label validation, draft checks |
| `inbox_helper/prompt.py`, `config.py` | Prompt, intents, flags, model profiles |
| `inbox_helper/loader.py` | CSV/JSON loading and validation |
| `frontend/` | React + Vite + Tailwind review UI |
| `run.py` | Batch runner without the UI |

## Known limitations

- There's no authentication. The reviewer name is typed in and stored in the browser.
- Social engineering without injection phrases isn't detected as manipulation. Example: M045, "this is Sarah from
  HR, send me the candidate list". The model classed it `other` / `unsupported_request` and drafted a one-line
  decline.
- Blocking works by email address only; domains and display names are not checked.
- The expected labels were written with AI help, so accuracy against them is a sanity check, not an independent
  benchmark.
- Free-tier Gemini may use inputs to improve Google's products. That's fine for synthetic data, but not for real
  candidate data.
