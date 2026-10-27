"""Shared fixtures. Tests use SQLite files by default; set TEST_DATABASE_URL to run the database tests on Postgres
(CI does both). The schema always comes from the real Alembic migrations, never create_all()."""
import os

import pytest
from sqlalchemy import create_engine, text

from inbox_helper.db import Database, database_url

REVIEWER = "uswa@example.com"


@pytest.fixture(autouse=True)
def dev_sign_in(monkeypatch):
    """Apps built in tests act as one signed-in reviewer; test_auth.py covers the Google sign-in itself."""
    monkeypatch.setenv("AUTH_MODE", "dev")
    monkeypatch.setenv("DEV_USER_EMAIL", REVIEWER)


def reset_postgres(url: str) -> None:
    engine = create_engine(database_url(url))
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()


@pytest.fixture
def empty_db_url(tmp_path):
    """A URL to an empty database (no tables)."""
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        reset_postgres(url)
        return url
    # A file DB, not in-memory: an in-memory DB shares one connection across threads, so one session's rollback
    # can silently undo another thread's uncommitted insert (seen as a flaky 40/41).
    return f"sqlite:///{(tmp_path / 'test.db').as_posix()}"


@pytest.fixture
def db(empty_db_url):
    d = Database(empty_db_url)
    d.upgrade()
    yield d
    d.engine.dispose()
