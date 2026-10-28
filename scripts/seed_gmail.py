"""Fill the test Gmail inbox with the synthetic messages, so "Fetch new emails" works on a controlled inbox.

    .venv\\Scripts\\python scripts\\seed_gmail.py                 # data/messages.csv
    .venv\\Scripts\\python scripts\\seed_gmail.py --limit 5       # just the first 5
    .venv\\Scripts\\python scripts\\seed_gmail.py --file other.csv

Needs GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and GMAIL_ACCOUNT in .env, and http://127.0.0.1:8765/ in the OAuth
client's authorised redirect URIs. It opens Google's consent screen for GMAIL_ACCOUNT and asks for gmail.insert
(put a message into the mailbox without sending it) and gmail.readonly (to skip messages already there). The token
is used for this run only and stored nowhere.

Messages are inserted, not sent: they show up in the inbox as if from the fictional candidates, dated as in the
file. Running again is safe; each message has a Message-ID like <M001@seed.inbox-helper.test> and is skipped if
it is already in the mailbox. The app fetches with GMAIL_QUERY (default: the last 30 days), so re-run this or widen
GMAIL_QUERY once the sample dates are older than that.
"""
import argparse
import base64
import http.server
import os
import secrets
import sys
import webbrowser
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime, formataddr
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from inbox_helper.auth import GOOGLE_AUTH_URL, GOOGLE_TOKEN_URL  # noqa: E402
from inbox_helper.gmail import GMAIL_API  # noqa: E402
from inbox_helper.loader import Message, load_messages  # noqa: E402

PORT = 8765
REDIRECT_URI = f"http://127.0.0.1:{PORT}/"
SCOPES = "https://www.googleapis.com/auth/gmail.insert https://www.googleapis.com/auth/gmail.readonly"
SEED_DOMAIN = "seed.inbox-helper.test"


def authorize(client_id: str, account: str) -> str:
    """Google's consent screen in the browser; returns the code Google sends back to the local redirect."""
    state, answer = secrets.token_urlsafe(16), {}

    class Callback(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            if q.get("state") == state:
                answer.update(q)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Done. Close this tab and go back to the terminal.")

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", PORT), Callback)
    url = GOOGLE_AUTH_URL + "?" + urlencode({
        "client_id": client_id, "redirect_uri": REDIRECT_URI, "response_type": "code", "scope": SCOPES,
        "state": state, "login_hint": account, "prompt": "consent"})
    print(f"Opening Google in your browser. Sign in as {account}.\nIf nothing opens, visit:\n{url}\n")
    webbrowser.open(url)
    while "code" not in answer and "error" not in answer:
        server.handle_request()
    server.server_close()
    if "error" in answer:
        sys.exit(f"Google said: {answer['error']}")
    return answer["code"]


def to_mime(m: Message, account: str) -> str:
    try:
        when = datetime.fromisoformat(m.received_at)
    except ValueError:
        when = datetime.now(timezone.utc)
    msg = EmailMessage()
    msg["From"] = formataddr((m.candidate_name, m.candidate_email or "unknown@example.com"))
    msg["To"] = account
    msg["Subject"] = m.subject
    msg["Date"] = format_datetime(when if when.tzinfo else when.replace(tzinfo=timezone.utc))
    msg["Message-ID"] = f"<{m.message_id}@{SEED_DOMAIN}>"
    msg.set_content(m.body)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--file", default=str(ROOT / "data" / "messages.csv"))
    parser.add_argument("--limit", type=int, default=0, help="only the first N messages")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    client_id, secret = os.environ.get("GOOGLE_CLIENT_ID", ""), os.environ.get("GOOGLE_CLIENT_SECRET", "")
    account = os.environ.get("GMAIL_ACCOUNT", "").strip().lower()
    if not (client_id and secret and account):
        sys.exit("Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and GMAIL_ACCOUNT in .env first.")

    messages = load_messages(args.file).messages
    messages = messages[:args.limit] if args.limit else messages

    code = authorize(client_id, account)
    r = requests.post(GOOGLE_TOKEN_URL, timeout=10, data={
        "code": code, "client_id": client_id, "client_secret": secret, "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code"})
    if r.status_code != 200:
        sys.exit(f"Google refused the token ({r.status_code}): {r.text[:300]}")
    gmail = requests.Session()
    gmail.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

    signed_in = gmail.get(f"{GMAIL_API}/profile", timeout=20).json().get("emailAddress", "").lower()
    if signed_in != account:
        sys.exit(f"You signed in as {signed_in}, not {account}. Nothing was added. Run again and pick {account}.")

    added = skipped = failed = 0
    for m in messages:
        found = gmail.get(f"{GMAIL_API}/messages", timeout=20,
                          params={"q": f"rfc822msgid:{m.message_id}@{SEED_DOMAIN}"}).json()
        if found.get("messages"):
            skipped += 1
            continue
        r = gmail.post(f"{GMAIL_API}/messages", params={"internalDateSource": "dateHeader"}, timeout=20,
                       json={"raw": to_mime(m, account), "labelIds": ["INBOX", "UNREAD"]})
        if r.status_code == 200:
            added += 1
            print(f"  added   {m.message_id}  {m.candidate_name}: {m.subject}")
        else:
            failed += 1
            print(f"  FAILED  {m.message_id}  ({r.status_code}) {r.text[:200]}")
    print(f"\n{added} added, {skipped} already there, {failed} failed. Now use 'Fetch new emails' in the app.")


if __name__ == "__main__":
    main()
