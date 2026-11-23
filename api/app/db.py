"""Database engine, base class for tables, and the session dependency. Card M1-04 owns this file.

Define a table in your module's `models.py`:

    from sqlalchemy.orm import Mapped, mapped_column
    from app.db import Base

    class Grant(Base):
        __tablename__ = "grants"
        id: Mapped[int] = mapped_column(primary_key=True)

Store enums with `enum_column(...)` and add `Timestamps` for created_at/updated_at.

Then add a migration for it (see api/migrations/README.md).

Use the database in an endpoint with the `DbSession` dependency:

    @router.post("/grants")
    def create_grant(body: GrantCreate, db: DbSession) -> Grant:
        db.add(...)
        db.commit()

Each request gets its own session. Nothing is saved until you call `db.commit()`; anything
not committed is rolled back when the request ends, including when it fails.
"""

import importlib
import importlib.util
import pkgutil
from collections.abc import Iterator
from datetime import datetime
from enum import StrEnum
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Connection, DateTime, Engine, Enum, MetaData, create_engine, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from app.config import get_settings

# Fixed names for indexes and constraints, so every migration names them the same way
# and a later migration can drop or change one by name. Never change this once migrations
# exist: enum CHECK constraints in existing migrations take their names from it at run time.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",  # every column, so names never clash
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Every table in every module inherits from this, so Alembic can see them all."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def enum_column(enum_cls: type[StrEnum], name: str) -> Enum:
    """Store a StrEnum (Role, Sensitivity, SourceType, ...) as its plain text value.

    The database gets a CHECK constraint listing the allowed values, so a bad value is refused
    even by code that skips the ORM. `name` names that constraint; use the column's name.

    Adding a value to the enum later needs a hand-written migration: `alembic check` does not
    compare CHECK constraints (tests/test_migrations.py does).
    """
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=20,
        values_callable=lambda members: [m.value for m in members],
        validate_strings=True,
    )


class Timestamps:
    """Adds created_at and updated_at, both set by the database.

    `onupdate` only fires for ORM updates, so each table also needs the `set_updated_at`
    trigger in its migration (see 0002); that covers raw SQL and upserts too.
    """

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


@lru_cache
def get_engine() -> Engine:
    """One connection pool for the whole process, created on first use. Outside tests, refuses
    to run as a superuser or table owner (see `check_app_login`)."""
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env.")
    engine = create_engine(
        settings.database_url,
        # Replace connections the database has closed, e.g. after a Postgres restart.
        pool_pre_ping=True,
        # Fail a request after 10 s if the database is unreachable, instead of hanging.
        connect_args={"connect_timeout": 10},
    )
    if settings.environment != "test":
        with engine.connect() as connection:
            check_app_login(connection)
    return engine


def check_app_login(connection: Connection) -> None:
    """Refuse a login that could edit the audit log: a superuser, or the owner of audit_events.

    The API must connect as its limited login (DATABASE_URL, see infra/postgres/README.md). An
    old .env pointing at the owner would otherwise run silently, relying only on triggers that a
    superuser can switch off.
    """
    superuser, owner = connection.execute(
        text(
            "SELECT r.rolsuper, EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'audit_events'"
            " AND tableowner = current_user) FROM pg_roles r WHERE r.rolname = current_user"
        )
    ).one()
    if superuser or owner:
        raise RuntimeError(
            "The API is connected to the database as a superuser or table owner. Set "
            "DATABASE_URL to the limited app login (copy .env.example to .env, then "
            "docker compose down -v). See infra/postgres/README.md."
        )


def import_all_models() -> None:
    """Import every `app/modules/<name>/models.py`, so all tables are registered on `Base`.

    Alembic and the test database need the full set of tables. Finding the files here means
    nobody has to add their module to a shared list.
    """
    import app.modules

    for module in pkgutil.iter_modules(app.modules.__path__):
        if module.ispkg and importlib.util.find_spec(f"app.modules.{module.name}.models"):
            importlib.import_module(f"app.modules.{module.name}.models")


def get_db() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


DbSession = Annotated[Session, Depends(get_db)]
