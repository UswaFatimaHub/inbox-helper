"""Load evals/goldens.json and turn each golden into app input, a reviewer checklist, and judge context."""
import json
from dataclasses import dataclass
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
ROOT = EVAL_DIR.parent
GOLDENS_PATH = EVAL_DIR / "goldens.json"
MESSAGE_FIELDS = ("candidate_name", "candidate_email", "role", "subject", "body")


@dataclass
class GoldenCase:
    id: str
    split: str             # "sample" (mirrors data/messages.csv) or "holdout" (new messages)
    category: str
    difficulty: str
    message: dict          # MESSAGE_FIELDS
    expected: dict         # acceptable_intents, required_flags, must_prioritise, reply_style, must, must_not, ...
    policy_refs: list[str]
    policy_context: list[str]
    reference_reply: str
    notes: str = ""


def load_goldens(path: Path = GOLDENS_PATH) -> tuple[dict, list[GoldenCase]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    excerpts = data["policy_excerpts"]
    cases = []
    for g in data["goldens"]:
        unknown = [r for r in g["policy_refs"] if r not in excerpts]
        if unknown:
            raise ValueError(f"{g['id']}: unknown policy_refs {unknown}")
        cases.append(GoldenCase(
            id=g["id"], split=g["split"], category=g["category"], difficulty=g["difficulty"],
            message={f: g["message"].get(f, "") for f in MESSAGE_FIELDS}, expected=g["expected"],
            policy_refs=g["policy_refs"], policy_context=[excerpts[r] for r in g["policy_refs"]],
            reference_reply=g["reference_reply"], notes=g.get("notes", "")))
    return data, cases


def render_message(case: GoldenCase) -> str:
    """The candidate message as the judge sees it."""
    m = case.message
    sender = m["candidate_name"] or "(no name)"
    role = f" (applied for: {m['role']})" if m["role"] else ""
    return f"From: {sender}{role}\nSubject: {m['subject']}\n\n{m['body']}"


def checklist(case: GoldenCase) -> list[str]:
    """Per-case ground truth for the policy-compliance judge: what the reply must and must not do."""
    e = case.expected
    return ([f"MUST: {x}" for x in e["must"]] + [f"MUST NOT: {x}" for x in e["must_not"]]
            + [f"POLICY: {x}" for x in case.policy_context])


def policy_sections(policy_text: str) -> list[str]:
    """Split the policy on '## ' headings; used as the retrieval context the drafts may draw facts from."""
    parts = policy_text.split("\n## ")
    return [parts[0].strip()] + [f"## {p.strip()}" for p in parts[1:] if p.strip()]


def as_input_records(cases: list[GoldenCase]) -> list[dict]:
    """Golden messages in the app's JSON input format, so live runs go through the real loader."""
    return [{"message_id": c.id, **c.message} for c in cases]
