"""Alembic environment. Used by the CLI ("alembic upgrade head") and by Database.upgrade(), which passes its own
connection in config.attributes so tests and the app migrate the exact engine they use."""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from inbox_helper.db import Base, database_url, lock_for_migration

config = context.config
if config.config_file_name and config.attributes.get("connection") is None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata,
                      render_as_batch=connection.dialect.name == "sqlite")  # SQLite cannot ALTER most things
    with context.begin_transaction():
        lock_for_migration(connection)
        context.run_migrations()


if context.is_offline_mode():
    context.configure(url=database_url(), target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
elif (conn := config.attributes.get("connection")) is not None:
    run_migrations(conn)
else:
    engine = create_engine(database_url())
    with engine.connect() as conn:
        run_migrations(conn)
    engine.dispose()
