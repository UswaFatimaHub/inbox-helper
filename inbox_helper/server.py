"""ASGI entry point: .venv\\Scripts\\python -m uvicorn inbox_helper.server:app --port 8000

Environment:
  DATABASE_URL      Postgres URL (postgres://, postgresql:// or postgresql+psycopg://); default .data/inbox.db
  AUTO_MIGRATE=0    do not apply pending migrations at startup (run "alembic upgrade head" yourself)
  EMBEDDED_WORKER=0 do not process runs in this process (run "python -m inbox_helper.worker" separately)
"""
import os

from .api import create_app
from .db import Database

db = Database()
if os.environ.get("AUTO_MIGRATE", "1") != "0":
    db.upgrade()
app = create_app(db, embedded_worker=os.environ.get("EMBEDDED_WORKER", "1") != "0")
