# Inbox Helper

Takes a pile of candidate messages, groups them by what the person wants, and drafts a short reply for each.
**Nothing is sent.** A person approves, edits or rejects every draft, and every action is recorded in an audit
trail. Approved replies can be copied, exported, or saved as Gmail drafts that a person sends from Gmail.

## Setup

Requires Python 3.12, Node 22 and a `.env` file in the project root (either API key alone works):

```
GEMINI_API_KEY=...
OPENROUTER_API_KEY=...
AUTH_MODE=dev          # local use without Google sign-in; see "Sign-in"
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

Open http://127.0.0.1:8000, then click **New triage** and either upload a CSV or JSON file or use the sample
inbox. With `AUTH_MODE=dev` you act as the local reviewer; with Google sign-in, your login is recorded on every
action. Drafts appear as the AI finishes them. Review the **Needs attention** group first.
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
| `AUTH_MODE` | `google` | `dev` turns sign-in off (local only); see "Sign-in" for the Google settings |

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

## Sign-in

Reviewers sign in with Google, and only the addresses in `ALLOWED_EMAILS` get in. The signed-in account is
recorded on every approval, edit, rejection and block. A reviewer name sent by the browser is ignored, so nobody
can act in someone else's name.

| Variable | Meaning |
|---|---|
| `AUTH_MODE` | `google` (default) or `dev` (no sign-in; every request acts as `DEV_USER_EMAIL`) |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | OAuth client, type "Web application" |
| `ALLOWED_EMAILS` | Comma-separated. `@company.com` allows a whole domain. Removing an address signs that person out on their next request |
| `SESSION_SECRET` | Long random string that signs the session cookie (Render generates it) |
| `PUBLIC_URL` | e.g. `http://127.0.0.1:8000`. Not needed on Render, which provides `RENDER_EXTERNAL_URL` |

- **Fails closed.** Every `/api` route needs a signed-in user except `/api/health` and `/api/auth/*`, including
  routes added later. With `AUTH_MODE=google` and a setting missing, the app refuses to start rather than run
  without a login.
- **Sessions.** A signed cookie lasts 8 hours. It is `HttpOnly` and `SameSite=Lax`, and `Secure` on HTTPS.
- **Google's answer is checked.** The app checks the `state` and `nonce`, then the token's issuer, audience,
  expiry and verified email.

Google Cloud setup (about 10 minutes, once):

1. In Google Cloud console → **APIs & Services** → **OAuth consent screen**, choose **External** and fill in
   the app name and your email. The scopes are only `openid`, `email` and `profile`, so no Google review is
   needed.
2. In **Credentials**, create an **OAuth client ID** of type **Web application**. Add these authorised redirect
   URIs:
   - `http://127.0.0.1:8000/api/auth/google/callback` (local testing)
   - `https://<your-service>.onrender.com/api/auth/google/callback`
3. To test sign-in locally, put `AUTH_MODE=google`, the client ID and secret, `ALLOWED_EMAILS`, a
   `SESSION_SECRET` and `PUBLIC_URL=http://127.0.0.1:8000` in `.env`.

The same Google project and OAuth client are used for Gmail (next section).

## Gmail (test inbox)

The app can work on one Gmail inbox instead of a file. **Fetch new emails** imports messages, and approving a
reply saves it as a **draft in the original thread**. A person opens Gmail and sends it. The app has no way to send:
`gmail.compose` would allow it, but no code calls a send endpoint, and `tests/test_gmail.py` fails if one is added.

| Variable | Meaning |
|---|---|
| `GMAIL_ACCOUNT` | The only mailbox that may be connected. Use a dedicated test account. Connecting any other mailbox is refused and its access revoked |
| `GMAIL_TOKEN_KEY` | Any long random string. Encrypts the stored refresh token. Changing it means connecting again (Render generates it) |
| `GMAIL_QUERY` | Optional. The Gmail search for **Fetch**; default `in:inbox -from:me newer_than:30d` |

Without `GMAIL_ACCOUNT` and `GMAIL_TOKEN_KEY`, Gmail is off and the New triage dialog says what is missing. The
Google client ID, secret and `PUBLIC_URL` are the sign-in ones.

How it behaves:

- **Connect.** Any signed-in reviewer clicks **Connect Gmail** in the New triage dialog and signs in to Google as
  `GMAIL_ACCOUNT`. The app asks for `gmail.readonly` and `gmail.compose`, and refuses if a box was unticked.
  Disconnecting revokes the access at Google.
- **Fetch.** Up to 50 messages not imported before become a normal run, with the same validation, redaction and
  quarantine as a file. The text part is used; an HTML-only email is converted to text. Quoted earlier messages and
  signatures (after a `-- ` line) are cut. Gmail ids are stored, so nothing is imported twice. Attachments are
  ignored.
- **Approve.** The reply becomes a draft: To the sender, `Re:` subject, `In-Reply-To`/`References` set, in the
  same thread. If that fails (Google down, connection expired), the approval stands, the message shows the error,
  and **Create Gmail draft** tries again.
- **Reopen.** The draft is deleted, so a reply that is being reconsidered can't be sent from Gmail by mistake.
  Re-approving creates a new one.
- **Expiry.** While the Google project is in Testing mode, Google's refresh tokens last 7 days. After that the
  dialog shows **Reconnect Gmail**.

Google Cloud setup, on top of the sign-in setup:

1. **APIs & Services → Library**: enable the **Gmail API**.
2. **Google Auth Platform → Audience**: keep the status at **Testing** and add the test account under **Test
   users**. **Data access**: add `gmail.readonly`, `gmail.compose` and, for the seeding script, `gmail.insert`.
   These are restricted scopes; publishing would need Google's security review, so the app stays in Testing mode
   and shows an "unverified app" warning on the consent screen.
3. In the OAuth client, add these redirect URIs:
   - `http://127.0.0.1:8000/api/gmail/callback` and `https://<your-service>.onrender.com/api/gmail/callback`
   - `http://127.0.0.1:8765/` (used only by the seeding script)

Fill the test inbox with the synthetic messages (47 valid ones from `data/messages.csv`), then use **Fetch new
emails**:

```powershell
.venv\Scripts\python scripts\seed_gmail.py
```

The script inserts the messages into the inbox without sending anything. They appear as if from the fictional
candidates, at the dates in the file. It is safe to run again: messages already there are skipped. All sample
addresses are on `example.com`, so a draft sent by mistake goes nowhere. The CSV's `role` column has no place in an
email, so imported messages have no role.

## Deploy to Render

`render.yaml` describes the whole deployment: a free Docker web service with the embedded worker, and a free
Postgres in the same region.

1. In Render, choose **New** → **Blueprint**, connect the GitHub repo, and apply `render.yaml`.
2. When asked, enter `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `ALLOWED_EMAILS`, `GEMINI_API_KEY`,
   `GMAIL_ACCOUNT` and optionally `OPENROUTER_API_KEY`. `SESSION_SECRET`, `GMAIL_TOKEN_KEY` and `DATABASE_URL` are
   filled in automatically.
3. Add the service URL's two callbacks (`/api/auth/google/callback` and `/api/gmail/callback`) to the Google OAuth
   client.

After that, a push to `master` deploys once the CI checks pass. Migrations run at startup.

What the free tier means:

- **Sleeping.** The service sleeps after 15 idle minutes, and the first request then takes about a minute.
- **Runs.** A run in progress keeps the service awake while the UI is open and polling. If the service sleeps
  mid-run anyway, the job is resumed on the next start, as described in "Runs survive restarts".
- **Database expiry.** Render's free Postgres expires after 30 days. Upgrade it, or export first, if the pilot
  runs longer.
- **Cache.** The model-output cache is on the container's disk, so it is lost on every deploy.
- **Data.** Synthetic data only, until a paid AI API with no-training terms is in place.

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

## Personal data is hidden from the AI

Before a message goes to any model, `inbox_helper/redact.py` swaps identifiers for tokens:

| Hidden | Becomes |
|---|---|
| CNIC (`35202-1234567-1`) | `[NATIONAL_ID]` |
| IBAN | `[IBAN]` |
| Card numbers (Luhn-checked) | `[CARD_NUMBER]` |
| Phone numbers | `[PHONE]` |
| Passport numbers (next to the word "passport") | `[PASSPORT]` |
| Email addresses in the text | `[EMAIL]` |
| Any other number with 9+ digits | `[NUMBER]` |

- **The reviewer still sees everything.** The stored message is the original; only the copy sent to the AI is
  redacted. The message gets the `personal_data_hidden` and `sensitive` flags, so it goes to the top of the
  review queue.
- **What is kept.** Names, because drafts greet the person by name. Dates, times, years, money amounts and short
  reference numbers are kept too, because drafts need them. Tests pin both sides.
- **Effect on the sample.** In the synthetic data, only M039 (CNIC and bank account number) contains identifiers.
  Its draft still tells the candidate not to email them, and the eval scores did not change.
- **Limits.** The rules are patterns, not a trained detector. Identifiers in unusual formats, addresses and
  free-text health details still reach the model. That is one reason real candidate data also needs a paid API
  with no-training terms.

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
| `inbox_helper/db.py` | SQLAlchemy models: runs, jobs, items, review_events, blocked_senders, gmail_account, gmail_messages |
| `inbox_helper/worker.py` | Job worker: claim, heartbeat, resume, fencing |
| `inbox_helper/auth.py` | Google sign-in, allowed-email list, session, login-required middleware |
| `inbox_helper/redact.py` | Hides identifiers from the AI |
| `inbox_helper/gmail.py` | Gmail: connect, fetch, drafts on approve (no send) |
| `scripts/seed_gmail.py` | Puts the synthetic messages into the test Gmail inbox |
| `render.yaml` | Render blueprint: web service + Postgres |
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

`.github/workflows/ci.yml` runs on every push and pull request. A manual run is available under
**Actions → CI → Run workflow**.

1. Backend tests on SQLite and on Postgres 17. Also runs `alembic upgrade head` and `alembic check` from scratch.
2. Frontend type check and build.
3. Dependency scan: `pip-audit` and `npm audit`.
4. Docker: builds the image, starts Postgres + web + worker, and checks health, the UI and the migration version.
5. **Eval gate.** Runs the real pipeline on all 63 goldens and fails if a metric scores below
   `evals/baseline.json` (see `evals/README.md`). Needs a `GEMINI_API_KEY` repository secret
   (`OPENROUTER_API_KEY` is optional and uses its 50/day quota). An unchanged prompt is served from the cache,
   so it costs no API calls.

**Status (2026-10-27).** All five jobs pass on GitHub
([first green run](https://github.com/UswaFatimaHub/inbox-helper/actions/runs/40500512664), about 3.5 minutes).
On that run:

- The eval gate regenerated 60 of the 63 outputs on an empty cache. It passed at 62/63, 62/63 and 60/63.
- `gemini-3.5-flash` returned "high demand" 503 errors on 4 batches. Those batches moved to the other lanes, and
  every golden still got a result.

**Not done yet.**
- Branch protection: until the checks are marked required, a red check does not block a merge.
- `actions/cache` and `actions/upload-artifact` are on v4, which targets the deprecated Node 20. GitHub runs them
  on Node 24 for now and shows a warning.

## Known limitations

- There is one role: every allowed reviewer can do everything, including unblocking senders. There are no
  admin or read-only accounts.
- The model-output cache is a JSON file per worker (`.cache/`). It is lost when a container is replaced. That
  only costs repeat API calls, and resumed runs skip finished messages anyway.
- Social engineering without injection phrases isn't detected as manipulation. Example: M045, "this is Sarah from
  HR, send me the candidate list". The model classed it `other` / `unsupported_request` and drafted a one-line
  decline.
- Blocking works by email address only; domains and display names are not checked.
- Gmail: the sender address is trusted as written. SPF/DKIM results are not checked yet, so a forged `From` could
  get the wrong address blocked or answered. One mailbox per deployment. Fetching is manual (no push
  notifications). A draft edited or deleted in Gmail is not noticed by the app.
- The expected labels were written with AI help, so accuracy against them is a sanity check, not an independent
  benchmark.
- Free-tier Gemini may use inputs to improve Google's products. That's fine for synthetic data, but not for real
  candidate data, even with identifiers hidden.
