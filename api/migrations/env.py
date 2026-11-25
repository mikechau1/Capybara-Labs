"""How Alembic connects and which tables it knows about. Card M1-04 owns this file."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.config import get_settings
from app.db import Base, import_all_models

config = context.config

# The test fixture runs migrations in-process and keeps its own logging.
if config.config_file_name is not None and not config.attributes.get("keep_logging"):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

import_all_models()
target_metadata = Base.metadata


def _database_url() -> str:
    # The test fixture passes its own URL. Otherwise migrations run as the owner
    # (MIGRATION_DATABASE_URL). There is no fallback to DATABASE_URL: that is the API's
    # limited login, which can't create or alter tables, so it would only fail confusingly.
    url = config.attributes.get("database_url") or get_settings().migration_database_url
    if not url:
        raise RuntimeError(
            "MIGRATION_DATABASE_URL is not set: migrations run as the database owner. "
            "Copy .env.example to .env, or set it for this command (see migrations/README.md)."
        )
    return url


def run_migrations_offline() -> None:
    """`alembic upgrade head --sql`: print the SQL instead of running it, e.g. for review."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(
        _database_url(),
        poolclass=pool.NullPool,
        # Give up after 10 s if the database is unreachable, instead of hanging.
        connect_args={"connect_timeout": 10},
    )
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        # PostgreSQL runs schema changes in a transaction, so a failed migration changes nothing.
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
