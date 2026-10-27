"""Initial schema: runs, items, review events, blocked senders (what create_all() made before Alembic).

Revision ID: 0001
Revises:
Create Date: 2026-10-27
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("finished_at", TZ),
        sa.Column("input_name", sa.String(255), nullable=False),
        sa.Column("profile", sa.String(32), nullable=False),
        sa.Column("prompt_version", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("total", sa.Integer, nullable=False),
        sa.Column("elapsed_s", sa.Float),
        sa.Column("error", sa.Text),
        sa.Column("input_errors", sa.JSON, nullable=False),
        sa.Column("lanes", sa.JSON, nullable=False),
    )
    op.create_table(
        "items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("run_id", sa.Integer, sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("message_id", sa.String(128), nullable=False),
        sa.Column("received_at", sa.String(64), nullable=False),
        sa.Column("candidate_name", sa.String(255), nullable=False),
        sa.Column("candidate_email", sa.String(255), nullable=False),
        sa.Column("role", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("intent", sa.String(40), nullable=False),
        sa.Column("secondary_intent", sa.String(40)),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("flags", sa.JSON, nullable=False),
        sa.Column("priority_review", sa.Boolean, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("draft_reply", sa.Text, nullable=False),
        sa.Column("lane", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(16), nullable=False),
        sa.Column("latency_s", sa.Float),
        sa.Column("error", sa.Text),
        sa.Column("processed_at", sa.String(64), nullable=False),
        sa.Column("review_status", sa.String(16), nullable=False),
        sa.Column("final_reply", sa.Text),
        sa.Column("reviewed_by", sa.String(80)),
        sa.Column("reviewed_at", TZ),
        sa.Column("review_note", sa.Text),
        sa.UniqueConstraint("run_id", "message_id"),
    )
    op.create_index("ix_items_run_id", "items", ["run_id"])
    op.create_index("ix_items_intent", "items", ["intent"])
    op.create_index("ix_items_review_status", "items", ["review_status"])
    op.create_table(
        "review_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id"), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("reviewer", sa.String(80), nullable=False),
        sa.Column("at", TZ, nullable=False),
        sa.Column("before_text", sa.Text),
        sa.Column("after_text", sa.Text),
        sa.Column("note", sa.Text),
    )
    op.create_index("ix_review_events_item_id", "review_events", ["item_id"])
    op.create_table(
        "blocked_senders",
        sa.Column("email", sa.String(255), primary_key=True),
        sa.Column("reason", sa.Text),
        sa.Column("blocked_by", sa.String(80), nullable=False),
        sa.Column("blocked_at", TZ, nullable=False),
        sa.Column("source_item_id", sa.Integer, sa.ForeignKey("items.id")),
    )


def downgrade() -> None:
    op.drop_table("blocked_senders")
    op.drop_table("review_events")
    op.drop_table("items")
    op.drop_table("runs")
