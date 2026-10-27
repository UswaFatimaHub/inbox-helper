"""Data fix: quarantine pending items from runs made before the manipulation rules existed (runs #1 and #2).

This used to run on every app start (api.requarantine_pending). It is a one-off correction, so it lives here and
runs once per database. The discarded draft is kept in the audit trail. A later rule change that should apply to
stored items needs its own migration.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-27
"""
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

SYSTEM_INTENTS = ("manipulation_attempt", "blocked_sender")
# config.QUARANTINE_KEEP_FLAGS as of this migration, frozen so later config changes do not alter what it did.
KEEP_FLAGS = {"prompt_injection", "injection_pattern", "blocked_sender", "non_english", "hostile_tone", "sensitive",
              "invalid_email", "duplicate_message"}

items = sa.table(
    "items", sa.column("id", sa.Integer), sa.column("subject", sa.String), sa.column("body", sa.Text),
    sa.column("intent", sa.String), sa.column("secondary_intent", sa.String), sa.column("flags", sa.JSON),
    sa.column("draft_reply", sa.Text), sa.column("final_reply", sa.Text), sa.column("priority_review", sa.Boolean),
    sa.column("reason", sa.Text), sa.column("review_status", sa.String))
events = sa.table(
    "review_events", sa.column("item_id", sa.Integer), sa.column("action", sa.String),
    sa.column("reviewer", sa.String), sa.column("at", sa.DateTime(timezone=True)),
    sa.column("before_text", sa.Text), sa.column("after_text", sa.Text), sa.column("note", sa.Text))


def upgrade() -> None:
    from inbox_helper.checks import detect_injection

    conn = op.get_bind()
    now = datetime.now(timezone.utc)
    pending = conn.execute(sa.select(items).where(items.c.review_status == "pending")).mappings().all()
    for it in pending:
        flags = list(it["flags"] or [])
        if it["intent"] in SYSTEM_INTENTS:
            # quarantined by an earlier version of the rules, which kept the AI's label and draft flags
            kept = sorted(f for f in flags if f in KEEP_FLAGS)
            if it["intent"] == "manipulation_attempt" and (it["secondary_intent"] or kept != sorted(flags)):
                conn.execute(items.update().where(items.c.id == it["id"]).values(secondary_intent=None, flags=kept))
            continue
        pattern = detect_injection(f"{it['subject']}\n{it['body']}")
        if not (pattern or "prompt_injection" in flags):
            continue
        conn.execute(events.insert().values(
            item_id=it["id"], action="quarantined", reviewer="system", at=now,
            before_text=it["final_reply"] if it["final_reply"] is not None else it["draft_reply"],
            note=f"Re-checked with current rules: manipulation attempt, draft discarded "
                 f"(AI had labelled it {it['intent']})"))
        conn.execute(items.update().where(items.c.id == it["id"]).values(
            intent="manipulation_attempt", secondary_intent=None,
            flags=sorted({f for f in flags if f in KEEP_FLAGS}
                         | {"prompt_injection", *(["injection_pattern"] if pattern else [])}),
            draft_reply="", final_reply=None, priority_review=True,
            reason=("Matches a known prompt-injection phrase." if pattern
                    else "The model flagged this message as prompt injection.")))


def downgrade() -> None:
    pass  # a data correction; the original drafts remain in review_events
