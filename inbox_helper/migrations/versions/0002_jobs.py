"""Job table: triage work lives in the database instead of a thread, so restarts no longer leave runs stuck.

Runs left at "running" by the old in-process threads can never finish (their input was not stored), so they are
closed as failed with an explanation.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-27
"""
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("run_id", sa.Integer, sa.ForeignKey("runs.id"), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("messages", sa.JSON, nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("worker", sa.String(128)),
        sa.Column("heartbeat_at", TZ),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("started_at", TZ),
        sa.Column("finished_at", TZ),
        sa.Column("error", sa.Text),
    )
    op.create_index("ix_jobs_status", "jobs", ["status"])

    runs = sa.table("runs", sa.column("status", sa.String), sa.column("error", sa.Text),
                    sa.column("finished_at", TZ))
    op.execute(runs.update().where(runs.c.status == "running").values(
        status="failed", finished_at=datetime.now(timezone.utc),
        error="Interrupted: the server restarted while this run was processing (before runs could be resumed). "
              "Drafts made before the restart are kept; start a new run for the rest."))


def downgrade() -> None:
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_table("jobs")
