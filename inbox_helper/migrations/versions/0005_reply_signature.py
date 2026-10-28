"""Greeting and sign-off move from the AI to code: items keep the AI's body separately (draft_body), and each
reviewer can set their own greeting and sign-off (reviewer_settings).

Existing drafts are backfilled: the greeting and sign-off the AI wrote are stripped (reply.strip_salutations), so old
drafts get the same layout and the reviewer's own greeting and sign-off too.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-29
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

items = sa.table("items", sa.column("id", sa.Integer), sa.column("draft_reply", sa.Text),
                 sa.column("draft_body", sa.Text))


def upgrade() -> None:
    from inbox_helper.reply import strip_salutations

    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "draft_body" not in {c["name"] for c in inspector.get_columns("items")}:  # create_all() databases have it
        op.add_column("items", sa.Column("draft_body", sa.Text))
    if not inspector.has_table("reviewer_settings"):
        op.create_table(
            "reviewer_settings",
            sa.Column("email", sa.String(255), primary_key=True),
            sa.Column("greeting", sa.Text),
            sa.Column("sign_off", sa.Text),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    for item_id, draft in conn.execute(sa.select(items.c.id, items.c.draft_reply).where(items.c.draft_body.is_(None))):
        conn.execute(items.update().where(items.c.id == item_id).values(draft_body=strip_salutations(draft or "")))


def downgrade() -> None:
    op.drop_table("reviewer_settings")
    op.drop_column("items", "draft_body")
