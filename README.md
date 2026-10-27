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
.venv\Scripts\python -m pip install -r requirements-dev.txt   # requirements.txt alone for production
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

Data is stored in SQLite at `.data/inbox.db`. To use Postgres, set `DATABASE_URL` (`postgres://`,
`postgresql://` and `postgresql+psycopg://` URLs all work). Pending database migrations are applied at startup.
The server also runs a background worker that processes triage runs (see "Runs survive restarts").

## Production-like stack: Docker + Postgres

```powershell
docker compose up --build      # Postgres + web + a separate worker; open http://127.0.0.1:8000
```

API keys are read from `.env` if it exists. On a host (Render, Fly.io, a VM) set `DATABASE_URL`, `GEMINI_API_KEY`
and/or `OPENROUTER_API_KEY` in the host's settings: the image contains no secrets, and HTTPS is terminated by the
host's proxy. `GET /api/health` is the health check.

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `.data/inbox.db` (SQLite) | Postgres URL in production |
| `EMBEDDED_WORKER` | `1` | `0`: this web process does not process runs; start `python -m inbox_helper.worker` separately |
| `AUTO_MIGRATE` | `1` | `0`: do not apply migrations at startup; run `alembic upgrade head` as a release step |
| `PORT` | `8000` | Port inside the container |

A single instance with the embedded worker is enough for one team. Compose runs a separate worker to show that
the two can be split.

## Database migrations (Alembic)

The schema is versioned in `inbox_helper/migrations/versions/`. Each schema change is a new migration script.
`alembic upgrade head` (or app startup) applies only the ones a database has not seen, and keeps its data.

```powershell
.venv\Scripts\alembic revision --autogenerate -m "add x to items"   # after changing db.py; review the file
.venv\Scripts\alembic upgrade head
.venv\Scripts\alembic check                                          # fails if db.py has changes with no migration
```

- A database created before Alembic existed (by `create_all()`) is recognised and upgraded in place.
- On Postgres, migrations take an advisory lock, so a web and a worker starting together do not both migrate.
- Data fixes are migrations too. `0002` closes runs that the old in-process threads left stuck at "running".
  `0003` is the one-off re-quarantine of injection messages from runs #1 and #2, which used to run on every
  startup.

## Runs survive restarts (job table)

Starting a run only stores it with its validated messages in the `jobs` table (status `queued`). A worker claims
the job and stores each result as it arrives. While it works, it updates a heartbeat every 10 s.

- **Worker dies mid-run** (deploy, crash, `docker compose kill worker`): after 60 s without a heartbeat, any worker
  takes the job over. It processes only the messages that have no result yet. Tested by killing the worker at 5/15
  messages: the new worker processed the other 10, and no message was stored twice.
- **No double processing.** On Postgres, `FOR UPDATE SKIP LOCKED` stops two workers from claiming the same job.
  A conditional `UPDATE` makes claims safe on SQLite too. A worker that lost its job cannot overwrite the new
  owner's result, and a unique (run, message) constraint drops duplicate rows.
- **No endless loops.** A job taken over 3 times is marked failed. **Retry** in the UI re-queues it, and the
  messages that already have drafts are kept.
- **No Redis.** Postgres already provides the queue and the locking. Redis would be worth adding if several
  workers needed one shared rate limit per provider. Today each worker has its own limiter, so two workers would
  together exceed the free-tier RPM.

## Other entry points

```powershell
.venv\Scripts\python run.py                        # batch run without the UI: writes out/results.json + out/review.csv
.venv\Scripts\python scripts\generate_dataset.py   # re-create the synthetic dataset and expected labels
.venv\Scripts\python -m pytest                      # tests (fake model clients, no API quota used)
$env:TEST_DATABASE_URL="postgresql://user:pass@localhost/test"; .venv\Scripts\python -m pytest   # same, on Postgres
.venv\Scripts\python -m inbox_helper.worker          # a standalone worker (with EMBEDDED_WORKER=0 on the server)
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
| `inbox_helper/api.py`, `server.py` | FastAPI: runs, items, review actions, export, audit, health |
| `inbox_helper/db.py` | SQLAlchemy models: runs, jobs, items, review_events, blocked_senders |
| `inbox_helper/worker.py` | Job worker: claim, heartbeat, resume, fencing |
| `inbox_helper/migrations/` | Alembic migrations (schema and data fixes) |
| `inbox_helper/pipeline.py` | Lane scheduler, retries, cache, result records |
| `inbox_helper/checks.py` | Output parsing, label validation, draft checks |
| `inbox_helper/prompt.py`, `config.py` | Prompt, intents, flags, model profiles |
| `inbox_helper/loader.py` | CSV/JSON loading and validation |
| `frontend/` | React + Vite + Tailwind review UI |
| `run.py` | Batch runner without the UI |
| `evals/` | deepeval suite, golden dataset, eval gate (`evals/README.md`) |
| `Dockerfile`, `docker-compose.yml` | Image (UI build + API) and the local Postgres stack |
| `.github/workflows/ci.yml` | CI: tests on SQLite and Postgres, frontend build, dependency scan, Docker smoke test, eval gate |

## CI

`.github/workflows/ci.yml` runs on every push and pull request:

1. Backend tests on SQLite and on Postgres 17. Also runs `alembic upgrade head` and `alembic check` from scratch.
2. Frontend type check and build.
3. Dependency scan: `pip-audit` and `npm audit`.
4. Docker: builds the image, starts Postgres + web + worker, and checks health, the UI and the migration version.
5. **Eval gate.** Runs the real pipeline on all 63 goldens and fails if a metric scores below
   `evals/baseline.json` (see `evals/README.md`). Needs a `GEMINI_API_KEY` repository secret
   (`OPENROUTER_API_KEY` is optional and uses its 50/day quota). An unchanged prompt is served from the cache,
   so it costs no API calls.

To block merges, make these checks required in the branch protection settings.

## Known limitations

- There's no authentication. The reviewer name is typed in and stored in the browser.
- The model-output cache is a JSON file per worker (`.cache/`). It is lost when a container is replaced. That
  only costs repeat API calls, and resumed runs skip finished messages anyway.
- Social engineering without injection phrases isn't detected as manipulation. Example: M045, "this is Sarah from
  HR, send me the candidate list". The model classed it `other` / `unsupported_request` and drafted a one-line
  decline.
- Blocking works by email address only; domains and display names are not checked.
- The expected labels were written with AI help, so accuracy against them is a sanity check, not an independent
  benchmark.
- Free-tier Gemini may use inputs to improve Google's products. That's fine for synthetic data, but not for real
  candidate data.
