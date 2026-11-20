"""Database engine, base class for tables, and the session dependency. Card M1-04 owns this file.

Define a table in your module's `models.py`:

    from sqlalchemy.orm import Mapped, mapped_column
    from app.db import Base

    class Grant(Base):
        __tablename__ = "grants"
        id: Mapped[int] = mapped_column(primary_key=True)

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
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine, MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, Session

from app.config import get_settings

# Fixed names for indexes and constraints, so every migration names them the same way
# and a later migration can drop or change one by name.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Every table in every module inherits from this, so Alembic can see them all."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


@lru_cache
def get_engine() -> Engine:
    """One connection pool for the whole process, created on first use."""
    url = get_settings().database_url
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env.")
    return create_engine(
        url,
        # Replace connections the database has closed, e.g. after a Postgres restart.
        pool_pre_ping=True,
        # Fail a request after 10 s if the database is unreachable, instead of hanging.
        connect_args={"connect_timeout": 10},
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
