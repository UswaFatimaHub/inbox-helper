"""Load candidate messages from CSV or JSON and validate them.

Fatal problems (unreadable file, missing columns) raise InputError with a message a recruiter can act on.
Row-level problems are collected so one bad row does not block the rest of the inbox.
"""
import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

REQUIRED_FIELDS = ("message_id", "body")
OPTIONAL_FIELDS = ("received_at", "candidate_name", "candidate_email", "role", "subject")
MAX_BODY_CHARS = 6000
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class InputError(Exception):
    """The input file cannot be used at all."""


@dataclass
class Message:
    message_id: str
    body: str
    received_at: str = ""
    candidate_name: str = ""
    candidate_email: str = ""
    role: str = ""
    subject: str = ""
    warnings: list[str] = field(default_factory=list)  # become code flags on the result


@dataclass
class RowError:
    row: int          # 1-based data row (CSV: excluding header) or JSON array index + 1
    message_id: str
    error: str


@dataclass
class LoadResult:
    messages: list[Message]
    errors: list[RowError]


def load_messages(path: str | Path) -> LoadResult:
    path = Path(path)
    if not path.exists():
        raise InputError(f"File not found: {path}")
    suffix = path.suffix.lower()
    if suffix not in (".csv", ".json"):
        raise InputError(f"Unsupported file type '{suffix or '(none)'}'. Use a .csv or .json file.")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as e:
        raise InputError(f"{path.name} is not valid UTF-8 text (byte {e.start}). Re-save it as UTF-8.") from None
    if not text.strip():
        raise InputError(f"{path.name} is empty.")
    records = _read_csv(text, path.name) if suffix == ".csv" else _read_json(text, path.name)
    return _validate(records)


def _read_csv(text: str, name: str) -> list[dict]:
    reader = csv.DictReader(text.splitlines())
    columns = [c.strip() for c in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED_FIELDS if c not in columns]
    if missing:
        raise InputError(
            f"{name} is missing required column(s): {', '.join(missing)}. "
            f"Found columns: {', '.join(columns) or '(none)'}.")
    rows = []
    for row in reader:
        if None in row:  # more cells than headers
            row = {k: v for k, v in row.items() if k is not None}
            row["_extra_cells"] = True
        rows.append({(k or "").strip(): v for k, v in row.items()})
    if not rows:
        raise InputError(f"{name} has a header row but no messages.")
    return rows


def _read_json(text: str, name: str) -> list[dict]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise InputError(f"{name} is not valid JSON: {e.msg} at line {e.lineno}, column {e.colno}.") from None
    if isinstance(data, dict) and isinstance(data.get("messages"), list):
        data = data["messages"]
    if not isinstance(data, list):
        raise InputError(f'{name} must contain a list of messages, or an object with a "messages" list.')
    if not data:
        raise InputError(f"{name} contains no messages.")
    return data


def _validate(records: list) -> LoadResult:
    messages, errors = [], []
    seen_ids: set[str] = set()
    seen_bodies: dict[str, str] = {}
    for i, rec in enumerate(records, start=1):
        if not isinstance(rec, dict):
            errors.append(RowError(i, "", "Entry is not an object with named fields."))
            continue
        mid = str(rec.get("message_id") or "").strip()
        body = str(rec.get("body") or "").strip()
        if not mid:
            errors.append(RowError(i, "", "Missing message_id."))
            continue
        if mid in seen_ids:
            errors.append(RowError(i, mid, f"Duplicate message_id '{mid}'; only the first occurrence is used."))
            continue
        if rec.get("_extra_cells"):
            errors.append(RowError(i, mid, "Row has more cells than the header (check for an unquoted comma)."))
            continue
        if not body:
            errors.append(RowError(i, mid, "Message body is empty; nothing to classify."))
            continue
        if len(body) > MAX_BODY_CHARS:
            errors.append(RowError(i, mid, f"Message body is {len(body)} characters; limit is {MAX_BODY_CHARS}."))
            continue
        seen_ids.add(mid)
        msg = Message(message_id=mid, body=body,
                      **{f: str(rec.get(f) or "").strip() for f in OPTIONAL_FIELDS})
        if msg.candidate_email and not EMAIL_RE.match(msg.candidate_email):
            msg.warnings.append("invalid_email")
        key = " ".join(body.lower().split())
        if key in seen_bodies:
            msg.warnings.append("duplicate_message")
        else:
            seen_bodies[key] = mid
        messages.append(msg)
    return LoadResult(messages, errors)
