"""Gmail import and drafts, against a fake Google (no network). The real HTTP calls are in gmail.Mailbox/GoogleApi."""
import ast
import base64
import email
import inspect
import time
from email import policy
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from inbox_helper import gmail as gmail_module
from inbox_helper.api import create_app
from inbox_helper.db import GmailAccount, GmailMessage
from inbox_helper.gmail import (SCOPES, GmailConfig, GmailError, GmailService, Mailbox, build_reply, clean_body,
                                html_to_text, parse_message)

from conftest import REVIEWER
from test_api import fake_lanes, wait_done

INBOX = "inbox@test.example"
CONFIG = GmailConfig("client-id", "client-secret", INBOX, "token-key", "http://testserver")


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def gmail_msg(gid: str, body: str = "", *, html: str | None = None, sender="Ali Khan <Ali@Example.com>",
              subject="Interview slot", ts: int = 1_793_000_000_000) -> dict:
    parts = [{"mimeType": "text/html" if html else "text/plain", "filename": "",
              "headers": [{"name": "Content-Type", "value": 'text/html; charset="UTF-8"'}] if html else [],
              "body": {"data": b64(html or body)}},
             {"mimeType": "application/pdf", "filename": "cv.pdf", "body": {"attachmentId": "a1"}}]
    return {"id": gid, "threadId": f"thread-{gid}", "internalDate": str(ts), "payload": {
        "mimeType": "multipart/mixed", "parts": parts, "headers": [
            {"name": "From", "value": sender}, {"name": "Subject", "value": subject},
            {"name": "Message-ID", "value": f"<{gid}@mail.example>"},
            {"name": "References", "value": "<earlier@mail.example>"}]}}


class FakeMailbox:
    def __init__(self, google: "FakeGoogle"):
        self.g = google

    def profile_email(self):
        return self.g.email

    def list_ids(self, query):
        self.g.queries.append(query)
        yield list(self.g.messages)

    def get(self, gmail_id):
        if self.g.on_get:
            self.g.on_get(gmail_id)
        return self.g.messages[gmail_id]

    def create_draft(self, raw, thread_id):
        if self.g.draft_error:
            raise GmailError(self.g.draft_error)
        draft_id = f"draft-{len(self.g.drafts) + len(self.g.deleted) + 1}"
        self.g.drafts[draft_id] = (email.message_from_bytes(base64.urlsafe_b64decode(raw), policy=policy.default),
                                   thread_id)
        return draft_id

    def delete_draft(self, draft_id):
        self.g.drafts.pop(draft_id, None)
        self.g.deleted.append(draft_id)


class FakeGoogle:
    def __init__(self):
        self.email = INBOX
        self.scope = " ".join(SCOPES)
        self.refresh_token: str | None = "refresh-secret"
        self.messages: dict[str, dict] = {}
        self.drafts: dict[str, tuple] = {}
        self.deleted: list[str] = []
        self.revoked: list[str] = []
        self.queries: list[str] = []
        self.draft_error: str | None = None
        self.expired = False
        self.on_get = None  # called with the id before each message download

    def exchange_code(self, config, code):
        assert code == "good-code"
        return {"access_token": "access-1", "refresh_token": self.refresh_token, "scope": self.scope,
                "expires_in": 3600}

    def refresh(self, config, refresh_token):
        assert refresh_token == "refresh-secret"
        if self.expired:
            raise GmailError("Google access to the inbox has expired or was revoked. Connect Gmail again.",
                             reconnect=True)
        return "access-2", time.time() + 3600

    def revoke(self, token):
        self.revoked.append(token)

    def mailbox(self, access_token):
        return FakeMailbox(self)


@pytest.fixture
def google():
    return FakeGoogle()


@pytest.fixture
def service(db, google):
    return GmailService(db, CONFIG, google)


@pytest.fixture
def client(db, service):
    app = create_app(db, lanes_factory=fake_lanes, use_cache=False, worker_poll_s=0.05, gmail=service)
    with TestClient(app) as c:
        yield c


def connect(client) -> TestClient:
    r = client.get("/api/gmail/connect", follow_redirects=False)
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    return client.get(f"/api/gmail/callback?code=good-code&state={state}", follow_redirects=False)


def fetch_run(client) -> list[dict]:
    r = client.post("/api/gmail/fetch")
    assert r.status_code == 200, r.text
    wait_done(client, r.json()["id"])
    return client.get(f"/api/runs/{r.json()['id']}/items").json()


# ---- connecting ---------------------------------------------------------------------------------------------
def test_without_settings_gmail_is_off_and_says_what_is_missing(db, monkeypatch):
    for k in ("GMAIL_ACCOUNT", "GMAIL_TOKEN_KEY"):
        monkeypatch.delenv(k, raising=False)
    app = create_app(db, lanes_factory=fake_lanes, embedded_worker=False)
    with TestClient(app) as c:
        status = c.get("/api/gmail/status").json()
        assert status["enabled"] is False and {"GMAIL_ACCOUNT", "GMAIL_TOKEN_KEY"} <= set(status["missing"])
        assert c.post("/api/gmail/fetch").status_code == 503
        assert c.get("/api/gmail/connect", follow_redirects=False).status_code == 503


def test_connect_asks_for_offline_access_to_the_configured_inbox(client):
    r = client.get("/api/gmail/connect", follow_redirects=False)
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["scope"] == [" ".join(SCOPES)] and q["login_hint"] == [INBOX]
    assert q["access_type"] == ["offline"] and q["prompt"] == ["consent"]
    assert q["redirect_uri"] == ["http://testserver/api/gmail/callback"]


def test_connect_stores_the_refresh_token_encrypted(client, db):
    r = connect(client)
    assert r.status_code == 307 and r.headers["location"] == "/?gmail=connected"
    status = client.get("/api/gmail/status").json()
    assert status["connected"] and status["connected_by"] == REVIEWER and status["error"] is None
    with db.Session() as s:
        stored = s.get(GmailAccount, INBOX).refresh_token
    assert "refresh-secret" not in stored
    assert gmail_module.decrypt_token("token-key", stored) == "refresh-secret"


def test_connecting_another_inbox_is_refused_and_its_grant_revoked(client, google):
    google.email = "me@personal.example"
    r = connect(client)
    assert r.status_code == 400 and "not the inbox this tool is set up for" in r.text
    assert google.revoked == ["refresh-secret"]
    assert client.get("/api/gmail/status").json()["connected"] is False


def test_connect_needs_both_scopes(client, google):
    google.scope = SCOPES[0]  # the user unticked "compose" on Google's screen
    r = connect(client)
    assert r.status_code == 400 and "gmail.compose" in r.text
    assert client.get("/api/gmail/status").json()["connected"] is False


def test_callback_with_a_wrong_state_is_refused(client):
    client.get("/api/gmail/connect", follow_redirects=False)
    r = client.get("/api/gmail/callback?code=good-code&state=forged", follow_redirects=False)
    assert r.status_code == 400 and "expired" in r.text.lower()


def test_disconnect_revokes_and_forgets(client, google):
    connect(client)
    assert client.post("/api/gmail/disconnect").status_code == 204
    assert google.revoked == ["refresh-secret"]
    assert client.get("/api/gmail/status").json()["connected"] is False


# ---- importing ----------------------------------------------------------------------------------------------
def test_fetch_before_connecting_says_to_connect(client):
    r = client.post("/api/gmail/fetch")
    assert r.status_code == 409 and "not connected" in r.json()["detail"]


def test_fetch_imports_new_messages_once(client, google, db):
    connect(client)
    google.messages = {"g1": gmail_msg("g1", "When is my interview?"), "g2": gmail_msg("g2", "I withdraw.")}
    items = fetch_run(client)
    assert sorted(i["message_id"] for i in items) == ["g1", "g2"]
    g1 = next(i for i in items if i["message_id"] == "g1")
    assert g1["candidate_email"] == "ali@example.com" and g1["candidate_name"] == "Ali Khan"
    assert g1["gmail"]["thread_id"] == "thread-g1" and g1["gmail"]["draft_id"] is None
    assert google.queries == [CONFIG.query]

    assert client.post("/api/gmail/fetch").json() == {"id": None, "imported": 0, "errors": []}
    google.messages["g3"] = gmail_msg("g3", "Any news?")
    assert [i["message_id"] for i in fetch_run(client)] == ["g3"]
    assert client.get("/api/gmail/status").json()["last_fetch_at"]


def test_status_shows_the_progress_of_a_running_fetch(client, google, service):
    connect(client)
    google.messages = {f"g{n}": gmail_msg(f"g{n}", f"Question number {n}?") for n in range(5)}
    seen = []
    google.on_get = lambda _: seen.append(service.status()["fetch"])
    assert client.get("/api/gmail/status").json()["fetch"] is None
    items = fetch_run(client)
    assert {i["message_id"] for i in items} == set(google.messages)  # parallel downloads, nothing lost
    assert {p["stage"] for p in seen} == {"downloading"} and all(p["found"] == 5 for p in seen)
    assert all(0 <= p["downloaded"] < 5 for p in seen) and seen[0]["started_at"]
    assert client.get("/api/gmail/status").json()["fetch"] is None


def test_messages_that_fail_validation_are_not_fetched_again(client, google, db):
    connect(client)
    google.messages = {"empty": gmail_msg("empty", "")}
    r = client.post("/api/gmail/fetch").json()
    assert r["id"] is None and r["errors"][0]["error"].startswith("Message body is empty")
    with db.Session() as s:
        assert s.get(GmailMessage, "empty").run_id is None
    assert client.post("/api/gmail/fetch").json()["errors"] == []


# ---- drafts -------------------------------------------------------------------------------------------------
def approve(client, item_id, text="Thanks Ali, the recruiter will confirm your slot."):
    return client.post(f"/api/items/{item_id}/review", json={"action": "approve", "text": text}).json()


def test_approving_creates_a_draft_reply_in_the_thread(client, google):
    connect(client)
    google.messages = {"g1": gmail_msg("g1", "When is my interview?")}
    [item] = fetch_run(client)
    done = approve(client, item["id"])
    assert done["review_status"] == "approved" and done["gmail"]["draft_id"] == "draft-1"
    assert done["events"][-1]["action"] == "drafted"
    msg, thread = google.drafts["draft-1"]
    assert thread == "thread-g1"
    assert msg["To"] == "Ali Khan <ali@example.com>" and msg["From"] == INBOX
    assert msg["Subject"] == "Re: Interview slot"
    assert msg["In-Reply-To"] == "<g1@mail.example>"
    assert msg["References"] == "<earlier@mail.example> <g1@mail.example>"
    assert msg.get_content().strip() == "Thanks Ali, the recruiter will confirm your slot."


def test_reopening_deletes_the_draft_so_it_cannot_be_sent(client, google):
    connect(client)
    google.messages = {"g1": gmail_msg("g1", "When is my interview?")}
    [item] = fetch_run(client)
    approve(client, item["id"])
    r = client.post(f"/api/items/{item['id']}/review", json={"action": "reopen"}).json()
    assert google.drafts == {} and google.deleted == ["draft-1"]
    assert r["gmail"]["draft_id"] is None and r["events"][-1]["action"] == "draft_deleted"
    again = approve(client, item["id"], "Edited reply.")
    assert again["gmail"]["draft_id"] == "draft-2"
    assert google.drafts["draft-2"][0].get_content().strip() == "Edited reply."


def test_a_failed_draft_keeps_the_approval_and_can_be_retried(client, google):
    connect(client)
    google.messages = {"g1": gmail_msg("g1", "When is my interview?")}
    [item] = fetch_run(client)
    google.draft_error = "Gmail answered 500: backend error"
    done = approve(client, item["id"])
    assert done["review_status"] == "approved" and done["gmail"]["draft_id"] is None
    assert "backend error" in done["gmail"]["draft_error"] and done["events"][-1]["action"] == "draft_failed"
    google.draft_error = None
    retried = client.post(f"/api/items/{item['id']}/gmail-draft").json()
    assert retried["gmail"]["draft_id"] and retried["gmail"]["draft_error"] is None
    assert client.post(f"/api/items/{item['id']}/gmail-draft").status_code == 409  # already has one


def test_expired_access_is_shown_and_the_draft_waits_for_a_reconnect(client, google, service):
    connect(client)
    google.messages = {"g1": gmail_msg("g1", "When is my interview?")}
    [item] = fetch_run(client)
    google.expired, service._access = True, None  # the cached access token ran out and Google refuses a new one
    done = approve(client, item["id"])
    assert done["review_status"] == "approved" and "Connect Gmail again" in done["gmail"]["draft_error"]
    assert "expired" in client.get("/api/gmail/status").json()["error"]
    google.expired = False
    connect(client)
    assert client.get("/api/gmail/status").json()["error"] is None
    assert client.post(f"/api/items/{item['id']}/gmail-draft").json()["gmail"]["draft_id"]


def test_messages_from_files_get_no_gmail_draft(client, google):
    connect(client)
    run_id = client.post("/api/runs/sample").json()["id"]
    wait_done(client, run_id)
    item = client.get(f"/api/runs/{run_id}/items").json()[0]
    assert item["gmail"] is None
    assert approve(client, item["id"])["gmail"] is None and google.drafts == {}
    assert client.post(f"/api/items/{item['id']}/gmail-draft").status_code == 400


def test_nothing_in_the_gmail_code_can_send_mail():
    # gmail.compose also allows sending; the only guarantee is that no code path calls a send endpoint.
    methods = [name for name, _ in inspect.getmembers(Mailbox, inspect.isfunction)]
    assert not [m for m in methods if "send" in m.lower()]
    strings = [n.value for n in ast.walk(ast.parse(inspect.getsource(gmail_module)))
               if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert not [s for s in strings if "/send" in s or s.rstrip("/").endswith("send")]


# ---- parsing ------------------------------------------------------------------------------------------------
def test_quoted_reply_and_signature_are_cut():
    text = ("Thanks, Tuesday works.\n\n-- \nAli Khan\n+92 300 1234567\n\n"
            "On Mon, 27 Oct 2026 at 10:00, Brightpath HR <hr@brightpath.example>\nwrote:\n> Can you do Tuesday?")
    assert clean_body(text) == "Thanks, Tuesday works."
    assert clean_body("Yes.\r\n> quoted line\r\nSee you then.") == "Yes.\nSee you then."


def test_html_body_becomes_text_without_the_quoted_part():
    html = ("<html><head><style>p{color:red}</style></head><body><p>Hello&nbsp;team,</p><div>Is the role "
            "<b>remote</b>?<br>Thanks</div><blockquote>earlier message</blockquote></body></html>")
    assert clean_body(html_to_text(html)) == "Hello team,\n\nIs the role remote?\nThanks"
    parsed = parse_message(gmail_msg("h1", html=html))
    assert parsed.body.startswith("Hello team,") and "earlier message" not in parsed.body


def test_reply_subject_is_not_prefixed_twice():
    gm = GmailMessage(gmail_id="x", thread_id="t", rfc_message_id="", references_header="", from_name="",
                      from_email="a@example.com", subject="RE: Offer")
    msg = email.message_from_bytes(base64.urlsafe_b64decode(build_reply(gm, INBOX, "Hi")), policy=policy.default)
    assert msg["Subject"] == "RE: Offer" and msg["In-Reply-To"] is None
