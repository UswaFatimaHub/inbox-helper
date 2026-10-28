"""Gmail: the connected mailbox, and the imported messages with what a reply in their thread needs.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-28
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "gmail_account",
        sa.Column("email", sa.String(255), primary_key=True),
        sa.Column("refresh_token", sa.Text, nullable=False),
        sa.Column("scopes", sa.Text, nullable=False),
        sa.Column("connected_by", sa.String(80), nullable=False),
        sa.Column("connected_at", TZ, nullable=False),
        sa.Column("last_fetch_at", TZ),
        sa.Column("error", sa.Text),
    )
    op.create_table(
        "gmail_messages",
        sa.Column("gmail_id", sa.String(64), primary_key=True),
        sa.Column("run_id", sa.Integer, sa.ForeignKey("runs.id")),
        sa.Column("thread_id", sa.String(64), nullable=False),
        sa.Column("rfc_message_id", sa.Text, nullable=False),
        sa.Column("references_header", sa.Text, nullable=False),
        sa.Column("from_name", sa.String(255), nullable=False),
        sa.Column("from_email", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("imported_at", TZ, nullable=False),
        sa.Column("draft_id", sa.String(64)),
        sa.Column("drafted_at", TZ),
        sa.Column("draft_error", sa.Text),
    )
    op.create_index("ix_gmail_messages_run_id", "gmail_messages", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_gmail_messages_run_id", table_name="gmail_messages")
    op.drop_table("gmail_messages")
    op.drop_table("gmail_account")
