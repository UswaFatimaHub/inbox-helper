"""Replies get a greeting and sign-off in the candidate's language: items.language, and a clean-up of drafts made
by prompt v5, where the model sometimes wrote its own greeting in another language ("Hi Maria,\\n\\nHola Maria,").

For each existing draft the language is read from the greeting the AI wrote (reply.greeting_language), the body is
stripped again with the multilingual rules, and draft_reply is rebuilt in the fixed layout.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-29
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

items = sa.table("items", sa.column("id", sa.Integer), sa.column("candidate_name", sa.String),
                 sa.column("draft_reply", sa.Text), sa.column("draft_body", sa.Text), sa.column("language", sa.String))


def upgrade() -> None:
    from inbox_helper.reply import compose, greeting_language, strip_salutations

    conn = op.get_bind()
    if "language" not in {c["name"] for c in sa.inspect(conn).get_columns("items")}:  # create_all() databases have it
        op.add_column("items", sa.Column("language", sa.String(8)))
    rows = conn.execute(sa.select(items.c.id, items.c.candidate_name, items.c.draft_reply, items.c.draft_body)
                        .where(items.c.draft_body.is_not(None), items.c.draft_body != "")).all()
    for item_id, name, draft, body in rows:
        # v5 drafts keep the AI's greeting in the body; older ones (stripped by 0005) still have it in draft_reply
        found = [lang for lang in (greeting_language(body), greeting_language(draft)) if lang and lang != "en"]
        language = found[0] if found else None
        body = strip_salutations(body, name or "")
        conn.execute(items.update().where(items.c.id == item_id).values(
            draft_body=body, language=language, draft_reply=compose(body, name or "", language=language)))


def downgrade() -> None:
    op.drop_column("items", "language")
