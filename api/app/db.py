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
    trigger in its migration (see 0002); that covers raw SQL and upserts too, and leaves the
    stamp alone when an UPDATE changes nothing.
    """

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


@lru_cache
def get_engine() -> Engine:
    """One connection pool for the whole process, created on first use. Outside tests, refuses
    to run as a login that could change the audit log (see `check_app_login`)."""
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
        try:
            with engine.connect() as connection:
                check_app_login(connection)
        except Exception:
            # lru_cache doesn't keep a failed call, so without this every request would leave
            # another privileged connection open.
            engine.dispose()
            raise
    return engine


# Every role the login (session_user, so SET ROLE can't hide it) can act as, directly, by
# inheritance or by SET ROLE, that could change or bypass the audit log: a superuser; the owner
# of audit_events, of its schema (who can drop it) or of a trigger function on it (who can
# replace the function); or a role holding UPDATE, DELETE, TRUNCATE or TRIGGER on it (TRIGGER
# could add a trigger that silently drops events). pg_write_all_data counts through the
# privilege check, which also reports every right for a superuser and normally for the owner;
# rolsuper and ownership are still checked on their own, since an owner can revoke its own
# rights and still disable the triggers.
_PRIVILEGED_ROLES = text(
    """
    WITH log AS (SELECT to_regclass('public.audit_events') AS oid)
    SELECT (SELECT oid FROM log) IS NULL,
           array(
               SELECT r.rolname FROM pg_roles r, log
               WHERE pg_has_role(session_user, r.oid, 'MEMBER')
                 AND (r.rolsuper
                      OR r.oid = (SELECT relowner FROM pg_class WHERE oid = log.oid)
                      OR r.oid = (SELECT n.nspowner FROM pg_class c
                                  JOIN pg_namespace n ON n.oid = c.relnamespace
                                  WHERE c.oid = log.oid)
                      OR r.oid IN (SELECT p.proowner FROM pg_trigger t
                                   JOIN pg_proc p ON p.oid = t.tgfoid
                                   WHERE t.tgrelid = log.oid)
                      OR has_table_privilege(r.oid, log.oid, 'UPDATE, DELETE, TRUNCATE, TRIGGER'))
               ORDER BY r.rolname
           )
    """
)


def check_app_login(connection: Connection) -> None:
    """Refuse a login that could change the audit log (see `_PRIVILEGED_ROLES`).

    The API must connect as its limited login (DATABASE_URL, see infra/postgres/README.md). An
    old .env pointing at the owner would otherwise run silently, relying only on triggers that
    the owner or a superuser can switch off.
    """
    missing, roles = connection.execute(_PRIVILEGED_ROLES).one()
    if missing:
        raise RuntimeError("The audit_events table doesn't exist: run the migrations first.")
    if roles:
        raise RuntimeError(
            f"The API's database login can act as {', '.join(roles)}, which can change the "
            "audit log (a superuser, an owner, or UPDATE, DELETE, TRUNCATE or TRIGGER rights). "
            "Set DATABASE_URL to the limited app login (copy .env.example to .env, then "
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
