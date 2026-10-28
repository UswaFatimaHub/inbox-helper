"""Gmail: import messages from one connected inbox and save approved replies as drafts in their threads.

Nothing here can send mail. The recruiter opens the draft in Gmail and sends it.

Setup (README "Gmail"):
  GMAIL_ACCOUNT     the only mailbox that may be connected (a dedicated test inbox); connecting another is refused
  GMAIL_TOKEN_KEY   any long random string; encrypts the stored refresh token (Render generates it)
  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and PUBLIC_URL as for sign-in, with PUBLIC_URL + /api/gmail/callback added
  to the OAuth client's redirect URIs. GMAIL_QUERY overrides the search used by "Fetch new emails".

Scopes: gmail.readonly (list and read messages) and gmail.compose (create and delete drafts). gmail.compose also
allows sending, and there is no drafts-only scope, so the guarantee is in the code: Mailbox has no send method and
calls no send endpoint, and tests/test_gmail.py fails if one appears.

Flow:
- Fetch: up to MAX_FETCH inbox messages not imported before become a normal run (same pipeline, same redaction).
  The Gmail ids are stored, so a message is never imported twice.
- Approve: the reply becomes a Gmail draft in the original thread. If that fails the approval stands, the error is
  shown on the message, and "Create Gmail draft" tries again.
- Reopen: the draft is deleted, so a reply that is being reconsidered cannot be sent from Gmail by mistake.
"""
import base64
import hashlib
import os
import re
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from html.parser import HTMLParser
from typing import Callable, Iterator
from urllib.parse import urlencode

import requests
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import delete, select

from .auth import GOOGLE_AUTH_URL, GOOGLE_TOKEN_URL, message_page
from .db import Database, GmailAccount, GmailMessage, Item, ReviewEvent, iso, utcnow
from .loader import validate_records

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
SCOPES = ("https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.compose")
CALLBACK_PATH = "/api/gmail/callback"
DEFAULT_QUERY = "in:inbox -from:me newer_than:30d"
MAX_FETCH = 50        # messages per "Fetch new emails"; the next click takes the next ones
MAX_LIST_PAGES = 10   # pages of 100 ids scanned per fetch while skipping messages imported before
DOWNLOAD_THREADS = 8  # parallel message downloads; well inside Gmail's per-user quota (messages.get = 5 units)


class GmailError(Exception):
    """A Gmail step failed. reconnect=True: there is no usable connection; a reviewer has to connect Gmail again."""

    def __init__(self, message: str, reconnect: bool = False):
        super().__init__(message)
        self.reconnect = reconnect


@dataclass(frozen=True)
class GmailConfig:
    client_id: str = ""
    client_secret: str = field(default="", repr=False)
    account: str = ""  # lower-cased
    token_key: str = field(default="", repr=False)
    public_url: str = "http://127.0.0.1:8000"
    query: str = DEFAULT_QUERY

    @classmethod
    def from_env(cls) -> "GmailConfig":
        def env(name: str) -> str:
            return os.environ.get(name, "").strip()
        public_url = env("PUBLIC_URL") or env("RENDER_EXTERNAL_URL") or "http://127.0.0.1:8000"
        return cls(env("GOOGLE_CLIENT_ID"), env("GOOGLE_CLIENT_SECRET"), env("GMAIL_ACCOUNT").lower(),
                   env("GMAIL_TOKEN_KEY"), public_url.rstrip("/"), env("GMAIL_QUERY") or DEFAULT_QUERY)

    @property
    def missing(self) -> list[str]:
        settings = {"GOOGLE_CLIENT_ID": self.client_id, "GOOGLE_CLIENT_SECRET": self.client_secret,
                    "GMAIL_ACCOUNT": self.account, "GMAIL_TOKEN_KEY": self.token_key}
        return [k for k, v in settings.items() if not v]

    @property
    def redirect_uri(self) -> str:
        return self.public_url + CALLBACK_PATH


# ---- token encryption ---------------------------------------------------------------------------------------
def _fernet(key: str) -> Fernet:
    # Any string works as GMAIL_TOKEN_KEY (Render generates one); Fernet needs exactly 32 bytes, so it is hashed.
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))


def encrypt_token(key: str, token: str) -> str:
    return _fernet(key).encrypt(token.encode()).decode()


def decrypt_token(key: str, blob: str) -> str:
    try:
        return _fernet(key).decrypt(blob.encode()).decode()
    except InvalidToken:
        raise GmailError("The stored Gmail connection cannot be read (GMAIL_TOKEN_KEY changed?). Connect Gmail again.",
                         reconnect=True) from None


# ---- Google -------------------------------------------------------------------------------------------------
def _google_message(r: requests.Response) -> str:
    try:
        body = r.json()
        err = body.get("error")
        return (err.get("message") if isinstance(err, dict) else body.get("error_description") or err) or r.reason
    except ValueError:
        return r.text[:200] or r.reason


class Mailbox:
    """The Gmail REST calls this tool makes, as the connected account. There is deliberately no send method:
    drafts are created and deleted, never sent."""

    def __init__(self, access_token: str):
        self.headers = {"Authorization": f"Bearer {access_token}"}

    def _call(self, method: str, path: str, missing_ok: bool = False, **kwargs) -> dict:
        try:
            r = requests.request(method, GMAIL_API + path, headers=self.headers, timeout=20, **kwargs)
        except requests.RequestException as e:
            raise GmailError(f"Gmail could not be reached ({e.__class__.__name__}). Try again.") from None
        if r.status_code == 404 and missing_ok:
            return {}
        if r.status_code == 401:
            raise GmailError("Google no longer accepts the Gmail connection. Connect Gmail again.", reconnect=True)
        if r.status_code >= 400:
            raise GmailError(f"Gmail answered {r.status_code}: {_google_message(r)}")
        return r.json() if r.content else {}

    def profile_email(self) -> str:
        return self._call("GET", "/profile")["emailAddress"].lower()

    def list_ids(self, query: str) -> Iterator[list[str]]:
        """Pages of ids of the messages matching query, newest first."""
        token = None
        for _ in range(MAX_LIST_PAGES):
            page = self._call("GET", "/messages", params={"q": query, "maxResults": 100,
                                                          **({"pageToken": token} if token else {})})
            yield [m["id"] for m in page.get("messages", [])]
            token = page.get("nextPageToken")
            if not token:
                return

    def get(self, gmail_id: str) -> dict:
        return self._call("GET", f"/messages/{gmail_id}", params={"format": "full"})

    def create_draft(self, raw: str, thread_id: str) -> str:
        return self._call("POST", "/drafts", json={"message": {"raw": raw, "threadId": thread_id}})["id"]

    def delete_draft(self, draft_id: str) -> None:
        self._call("DELETE", f"/drafts/{draft_id}", missing_ok=True)  # already sent or deleted in Gmail: fine


class GoogleApi:
    """Google's OAuth endpoints, and the mailbox they unlock. Tests replace this with a fake."""

    def _token(self, config: GmailConfig, data: dict) -> dict:
        try:
            r = requests.post(GOOGLE_TOKEN_URL, timeout=10,
                              data={"client_id": config.client_id, "client_secret": config.client_secret, **data})
        except requests.RequestException as e:
            raise GmailError(f"Google could not be reached ({e.__class__.__name__}). Try again.") from None
        if r.status_code in (400, 401) and data["grant_type"] == "refresh_token":
            # invalid_grant: revoked, or expired (tokens of an app in Testing mode last 7 days)
            raise GmailError("Google access to the inbox has expired or was revoked. Connect Gmail again.",
                             reconnect=True)
        if r.status_code != 200:
            raise GmailError(f"Google refused the Gmail connection ({r.status_code}: {_google_message(r)}).")
        return r.json()

    def exchange_code(self, config: GmailConfig, code: str) -> dict:
        return self._token(config, {"code": code, "redirect_uri": config.redirect_uri,
                                    "grant_type": "authorization_code"})

    def refresh(self, config: GmailConfig, refresh_token: str) -> tuple[str, float]:
        """A fresh access token and when it expires (epoch seconds)."""
        d = self._token(config, {"refresh_token": refresh_token, "grant_type": "refresh_token"})
        return d["access_token"], time.time() + d.get("expires_in", 3600)

    def revoke(self, token: str) -> None:
        try:
            requests.post(REVOKE_URL, data={"token": token}, timeout=10)
        except requests.RequestException:
            pass  # best effort; the user can also remove access at myaccount.google.com/permissions

    def mailbox(self, access_token: str) -> Mailbox:
        return Mailbox(access_token)


# ---- reading messages ---------------------------------------------------------------------------------------
@dataclass
class ParsedEmail:
    gmail_id: str
    thread_id: str
    rfc_message_id: str
    references: str
    from_name: str
    from_email: str
    subject: str
    received_at: str
    body: str

    def record(self) -> dict:
        """The message as the loader validates it; the Gmail id is the message id."""
        return {"message_id": self.gmail_id, "body": self.body, "received_at": self.received_at,
                "candidate_name": self.from_name, "candidate_email": self.from_email, "subject": self.subject}

    def row(self) -> GmailMessage:
        return GmailMessage(gmail_id=self.gmail_id, thread_id=self.thread_id, rfc_message_id=self.rfc_message_id,
                            references_header=self.references, from_name=self.from_name[:255],
                            from_email=self.from_email[:255], subject=self.subject[:500])


def header(part: dict, name: str) -> str:
    for h in part.get("headers", []):
        if h["name"].lower() == name.lower():
            try:
                return str(make_header(decode_header(h["value"]))).strip()
            except (UnicodeError, LookupError, ValueError):
                return h["value"].strip()
    return ""


def _part_text(part: dict) -> str:
    data = part["body"]["data"]
    raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    charset = re.search(r'charset="?([\w.-]+)', header(part, "Content-Type"), re.I)
    try:
        return raw.decode(charset.group(1) if charset else "utf-8", errors="replace")
    except LookupError:  # unknown charset name
        return raw.decode("utf-8", errors="replace")


class _HtmlText(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol"}
    SKIP = {"script", "style", "head", "blockquote"}  # blockquote: the earlier message being replied to

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(re.sub(r"\s+", " ", data))


def html_to_text(html: str) -> str:
    parser = _HtmlText()
    parser.feed(html)
    parser.close()
    return "\n".join(line.strip() for line in "".join(parser.out).split("\n"))


def body_text(payload: dict) -> str:
    """The text/plain part, or else the text/html part as text. Attachments are ignored."""
    found: dict[str, list[str]] = {"text/plain": [], "text/html": []}

    def walk(part: dict) -> None:
        if part.get("mimeType") in found and not part.get("filename") and part.get("body", {}).get("data"):
            found[part["mimeType"]].append(_part_text(part))
        for sub in part.get("parts") or []:
            walk(sub)

    walk(payload)
    return "\n".join(found["text/plain"]) or html_to_text("\n".join(found["text/html"]))


# "On Mon, 27 Oct 2026 at 10:00, Name <a@b.com> wrote:" (Gmail may wrap it onto two lines), Outlook's separators
QUOTE_START = re.compile(r"^(On\b[^\n]{0,200}(\n[^\n]{0,200})?\bwrote:|-{2,} ?Original Message ?-{2,}|_{10,})[ \t]*$",
                         re.M | re.I)


# HTML comments left in plain-text parts, e.g. Outlook conditionals "<!--[if !mso]><!-->" and "<![endif]-->"
HTML_COMMENT = re.compile(r"<!--.*?-->|<!\[(?:if|endif)[^>]*>|<!--\[if[^>]*>", re.S | re.I)


def clean_body(text: str) -> str:
    """Only what the sender wrote this time: quoted replies and the signature are cut."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    text = HTML_COMMENT.sub("", text)
    if m := QUOTE_START.search(text):
        text = text[:m.start()]
    lines = []
    for line in text.split("\n"):
        if line.rstrip() == "--":  # "-- " is the standard signature separator
            break
        if not line.lstrip().startswith(">"):
            lines.append(line.rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def parse_message(m: dict) -> ParsedEmail:
    p = m.get("payload", {})
    name, addr = parseaddr(header(p, "From"))
    received = datetime.fromtimestamp(int(m.get("internalDate", 0)) / 1000, timezone.utc)
    return ParsedEmail(gmail_id=m["id"], thread_id=m.get("threadId", ""), rfc_message_id=header(p, "Message-ID"),
                       references=header(p, "References"), from_name=name, from_email=addr.lower(),
                       subject=header(p, "Subject"), received_at=received.isoformat(timespec="minutes"),
                       body=clean_body(body_text(p)))


def build_reply(gm: GmailMessage, mailbox: str, text: str) -> str:
    """The reply as a raw MIME message (base64url) in the original thread. Gmail threads it by threadId, the
    In-Reply-To / References headers and a matching subject."""
    msg = EmailMessage()
    msg["From"] = mailbox
    msg["To"] = formataddr((gm.from_name, gm.from_email))
    msg["Subject"] = gm.subject if re.match(r"re:", gm.subject, re.I) else f"Re: {gm.subject}".strip()
    if gm.rfc_message_id:
        msg["In-Reply-To"] = gm.rfc_message_id
        msg["References"] = f"{gm.references_header} {gm.rfc_message_id}".strip()
    msg.set_content(text)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


# ---- the connected inbox ------------------------------------------------------------------------------------
@dataclass
class FetchProgress:
    """How far the running "Fetch new emails" has got, for the UI to poll via /api/gmail/status. In memory: one
    web process does the fetching (a second fetch is refused while one runs)."""
    stage: str = "searching"  # searching (listing ids) | downloading | queueing (validating, creating the run)
    found: int = 0
    downloaded: int = 0
    started_at: str = field(default_factory=lambda: iso(utcnow()))


class GmailService:
    """One connected mailbox per deployment: GMAIL_ACCOUNT, a dedicated test inbox during the pilot."""

    def __init__(self, db: Database, config: GmailConfig | None = None, google: GoogleApi | None = None):
        self.db = db
        self.config = config or GmailConfig.from_env()
        self.google = google or GoogleApi()
        self._access: tuple[str, float] | None = None  # cached access token and its expiry
        self.fetch_lock = threading.Lock()
        self.fetching: FetchProgress | None = None  # set while a fetch runs

    @property
    def enabled(self) -> bool:
        return not self.config.missing

    def _account(self, s) -> GmailAccount | None:
        return s.get(GmailAccount, self.config.account) if self.config.account else None

    def status(self) -> dict:
        d = {"enabled": self.enabled, "missing": self.config.missing, "account": self.config.account,
             "connected": False, "connected_by": None, "connected_at": None, "last_fetch_at": None, "error": None,
             "fetch": asdict(self.fetching) if self.fetching else None}
        if self.enabled:
            with self.db.Session() as s:
                if acc := self._account(s):
                    d.update(connected=True, connected_by=acc.connected_by, connected_at=iso(acc.connected_at),
                             last_fetch_at=iso(acc.last_fetch_at), error=acc.error)
        return d

    def auth_url(self, state: str) -> str:
        return GOOGLE_AUTH_URL + "?" + urlencode({
            "client_id": self.config.client_id, "redirect_uri": self.config.redirect_uri, "response_type": "code",
            "scope": " ".join(SCOPES), "state": state, "login_hint": self.config.account,
            "access_type": "offline", "prompt": "consent"})  # consent: Google only sends a refresh token then

    def connect(self, code: str, by: str) -> None:
        tokens = self.google.exchange_code(self.config, code)
        refresh, granted = tokens.get("refresh_token"), set(tokens.get("scope", "").split())
        try:
            if missing := [s.rpartition("/")[2] for s in SCOPES if s not in granted]:
                raise GmailError(f"Google did not grant {', '.join(missing)}. Connect again and tick every box on "
                                 f"Google's screen.")
            email = self.google.mailbox(tokens["access_token"]).profile_email()
            if email != self.config.account:
                raise GmailError(f"{email} is not the inbox this tool is set up for. Connect {self.config.account}.")
            if not refresh:
                raise GmailError("Google sent no refresh token. Connect again.")
        except GmailError:
            self.google.revoke(refresh or tokens["access_token"])  # do not leave an unused grant behind
            raise
        with self.db.write_lock, self.db.Session() as s:
            s.execute(delete(GmailAccount))
            s.add(GmailAccount(email=email, refresh_token=encrypt_token(self.config.token_key, refresh),
                               scopes=" ".join(sorted(granted)), connected_by=by))
            s.commit()
        self._access = (tokens["access_token"], time.time() + tokens.get("expires_in", 3600))

    def disconnect(self) -> None:
        with self.db.write_lock, self.db.Session() as s:
            if acc := self._account(s):
                try:
                    self.google.revoke(decrypt_token(self.config.token_key, acc.refresh_token))
                except GmailError:
                    pass  # unreadable token: nothing to revoke from here
            s.execute(delete(GmailAccount))
            s.commit()
        self._access = None

    def _mailbox(self) -> Mailbox:
        if not self.enabled:
            raise GmailError(f"Gmail is not set up on this server: set {', '.join(self.config.missing)}.")
        with self.db.Session() as s:
            acc = self._account(s)
            if acc is None:
                raise GmailError("Gmail is not connected. Connect it under New triage.", reconnect=True)
            blob = acc.refresh_token
        if not self._access or self._access[1] < time.time() + 60:
            self._access = self.google.refresh(self.config, decrypt_token(self.config.token_key, blob))
        return self.google.mailbox(self._access[0])

    @contextmanager
    def _gmail(self) -> Iterator[Mailbox]:
        """The mailbox; when Google stops accepting the connection, the reason is shown until someone reconnects."""
        try:
            yield self._mailbox()
        except GmailError as e:
            if e.reconnect:
                self._access = None
                with self.db.write_lock, self.db.Session() as s:
                    if acc := self._account(s):
                        acc.error = str(e)
                        s.commit()
            raise

    # ---- import ---------------------------------------------------------------------------------------------
    def fetch_new(self) -> list[ParsedEmail]:
        """Up to MAX_FETCH messages matching GMAIL_QUERY that were not imported before, newest first."""
        progress = self.fetching or FetchProgress()
        with self._gmail() as mailbox:
            new: list[str] = []
            for page in mailbox.list_ids(self.config.query):
                with self.db.Session() as s:
                    known = set(s.scalars(select(GmailMessage.gmail_id).where(GmailMessage.gmail_id.in_(page))))
                new += [i for i in page if i not in known]
                progress.found = min(len(new), MAX_FETCH)
                if len(new) >= MAX_FETCH:
                    break
            progress.stage = "downloading"

            def download(gmail_id: str) -> ParsedEmail:
                email = parse_message(mailbox.get(gmail_id))
                progress.downloaded += 1  # only a progress display; a lost increment would not matter
                return email

            with ThreadPoolExecutor(DOWNLOAD_THREADS) as pool:
                emails = list(pool.map(download, new[:MAX_FETCH]))  # map keeps the newest-first order
        with self.db.write_lock, self.db.Session() as s:
            if acc := self._account(s):
                acc.last_fetch_at = utcnow()
                s.commit()
        return emails

    def remember(self, rows: list[GmailMessage]) -> None:
        """Store imported messages that produced no run (none was valid), so they are not fetched again."""
        with self.db.write_lock, self.db.Session() as s:
            s.add_all(rows)
            s.commit()

    # ---- drafts ---------------------------------------------------------------------------------------------
    def message_for(self, s, item: Item) -> GmailMessage | None:
        gm = s.get(GmailMessage, item.message_id)
        return gm if gm is not None and gm.run_id == item.run_id else None

    def item_info(self, gm: GmailMessage | None) -> dict | None:
        if gm is None:
            return None
        return {"mailbox": self.config.account, "thread_id": gm.thread_id, "draft_id": gm.draft_id,
                "drafted_at": iso(gm.drafted_at), "draft_error": gm.draft_error}

    def _record(self, item: Item, gmail_id: str, action: str, note: str | None, by: str, **fields) -> None:
        with self.db.write_lock, self.db.Session() as s:
            gm = s.get(GmailMessage, gmail_id)
            for k, v in fields.items():
                setattr(gm, k, v)
            s.add(ReviewEvent(item_id=item.id, action=action, reviewer=by, note=note))
            s.commit()

    def create_draft(self, item: Item, by: str) -> None:
        """Save the approved reply as a Gmail draft in the original thread. A failure is recorded on the message,
        where the UI offers a retry; the approval stands either way. No-op for messages not from Gmail."""
        with self.db.Session() as s:
            gm = self.message_for(s, item)
        if gm is None or item.review_status != "approved":
            return
        try:
            with self._gmail() as mailbox:
                if gm.draft_id:  # left over from an earlier approval whose draft could not be deleted on reopen
                    mailbox.delete_draft(gm.draft_id)
                draft_id = mailbox.create_draft(build_reply(gm, self.config.account, item.final_reply or ""),
                                                gm.thread_id)
        except GmailError as e:
            self._record(item, gm.gmail_id, "draft_failed", str(e), by, draft_error=str(e))
            return
        self._record(item, gm.gmail_id, "drafted", f"Gmail draft {draft_id}", by,
                     draft_id=draft_id, drafted_at=utcnow(), draft_error=None)

    def delete_draft(self, item: Item, by: str) -> None:
        """On reopen: a reply that is being reconsidered must not wait in Gmail, where it could be sent."""
        with self.db.Session() as s:
            gm = self.message_for(s, item)
        if gm is None or not gm.draft_id:
            return
        try:
            with self._gmail() as mailbox:
                mailbox.delete_draft(gm.draft_id)
        except GmailError as e:
            error = f"The Gmail draft of the earlier approval is still in Gmail ({e}). Delete it there."
            self._record(item, gm.gmail_id, "draft_failed", error, by, draft_error=error)
            return
        self._record(item, gm.gmail_id, "draft_deleted", f"Gmail draft {gm.draft_id}", by,
                     draft_id=None, drafted_at=None, draft_error=None)


def gmail_router(service: GmailService, start_run: Callable[..., int]) -> APIRouter:
    """start_run(loaded, input_name, related) queues a run, storing the related rows in the same transaction."""
    router = APIRouter()

    def require_setup() -> None:
        if not service.enabled:
            raise HTTPException(503, f"Gmail is not set up on this server: set {', '.join(service.config.missing)}.")

    @router.get("/api/gmail/status")
    def status():
        return service.status()

    @router.get("/api/gmail/connect")
    def connect(request: Request):
        require_setup()
        state = secrets.token_urlsafe(24)
        request.session["gmail_oauth"] = {"state": state, "at": int(time.time())}
        return RedirectResponse(service.auth_url(state))

    @router.get(CALLBACK_PATH)
    def callback(request: Request, code: str = "", state: str = "", error: str = ""):
        pending = request.session.pop("gmail_oauth", None)
        if error:
            return message_page("Gmail not connected", "Google did not connect the inbox. Go back and try again.", 400)
        if not pending or not code or not secrets.compare_digest(state, pending["state"]) \
                or time.time() - pending["at"] > 600:
            return message_page("Link expired", "The Gmail connect link was stale or already used. Start again.", 400)
        try:
            service.connect(code, request.state.user.email)
        except GmailError as e:
            return message_page("Gmail not connected", str(e), 400)
        return RedirectResponse("/?gmail=connected")

    @router.post("/api/gmail/disconnect", status_code=204)
    def disconnect():
        service.disconnect()
        return Response(status_code=204)

    @router.post("/api/gmail/fetch")
    def fetch():
        require_setup()
        if not service.fetch_lock.acquire(blocking=False):
            raise HTTPException(409, "Emails are already being fetched.")
        service.fetching = FetchProgress()
        try:
            try:
                emails = service.fetch_new()
            except GmailError as e:  # 409: connect (again) first; 502: Google failed
                raise HTTPException(409 if e.reconnect else 502, str(e))
            if not emails:
                return {"id": None, "imported": 0, "errors": []}
            service.fetching.stage = "queueing"
            loaded = validate_records([e.record() for e in emails])
            rows = [e.row() for e in emails]
            errors = [{"row": e.row, "message_id": e.message_id, "error": e.error} for e in loaded.errors]
            if not loaded.messages:
                service.remember(rows)
                return {"id": None, "imported": 0, "errors": errors}
            run_id = start_run(loaded, f"Gmail: {service.config.account}", rows)
            return {"id": run_id, "imported": len(loaded.messages), "errors": errors}
        finally:
            service.fetching = None
            service.fetch_lock.release()

    return router
