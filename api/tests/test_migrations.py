"""Migrations match the models, in both directions, including what `alembic check` misses.

`alembic check` compares tables, columns and indexes, but not CHECK constraints (so a new enum
value slips through) or triggers. These tests cover those gaps for every table, so later cards
get the same protection without writing their own.
"""

import re
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, Enum, create_engine, make_url, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db import Base, import_all_models
from app.modules.sources.models import SYNC_STATUSES
from tests.conftest import API_ROOT, _skip_or_fail, _TestDatabaseSettings

import_all_models()


def _differences(engine: Engine) -> list:
    with engine.connect() as conn:
        context = MigrationContext.configure(conn, opts={"compare_type": True})
        return compare_metadata(context, Base.metadata)


@pytest.fixture
def scratch_engine() -> Iterator[tuple[Engine, Config]]:
    """An empty database of its own, so going down to base cannot disturb other tests."""
    url = make_url(_TestDatabaseSettings().url())
    name = f"{url.database}_migrations_test"
    server = create_engine(
        url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 3},
    )
    try:
        with server.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError as exc:
        _skip_or_fail(f"No test database server: {exc.orig}")

    scratch_url = url.set(database=name)
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.attributes["database_url"] = scratch_url.render_as_string(hide_password=False)
    config.attributes["keep_logging"] = True
    engine = create_engine(scratch_url)
    try:
        yield engine, config
    finally:
        engine.dispose()
        with server.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        server.dispose()


def test_migrations_go_up_and_down_and_match_the_models(scratch_engine):
    engine, config = scratch_engine

    command.upgrade(config, "head")
    assert _differences(engine) == []

    command.downgrade(config, "base")
    with engine.connect() as conn:
        tables = conn.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
        assert list(tables) == ["alembic_version"]
        functions = conn.scalar(
            text("SELECT count(*) FROM pg_proc WHERE proname = 'set_updated_at'")
        )
        assert functions == 0

    command.upgrade(config, "head")
    assert _differences(engine) == []


def _check_values(db: Session, table: str, constraint: str) -> set[str]:
    definition = db.scalar(
        text(
            "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
            "JOIN pg_class t ON t.oid = c.conrelid WHERE t.relname = :t AND c.conname = :c"
        ),
        {"t": table, "c": f"ck_{table}_{constraint}"},
    )
    assert definition, f"no CHECK constraint ck_{table}_{constraint}"
    return set(re.findall(r"'([^']*)'", definition))


def test_enum_columns_match_their_database_checks(db: Session):
    """Fails when an enum gains or loses a value without a migration changing its CHECK."""
    checked = 0
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if isinstance(column.type, Enum):
                expected = set(column.type.enums)
                assert _check_values(db, table.name, column.type.name) == expected, (
                    f"{table.name}.{column.name}: the enum and the database CHECK differ; "
                    "add a migration that recreates the constraint"
                )
                checked += 1
    assert checked > 0
    assert _check_values(db, "sources", "last_sync_status") == set(SYNC_STATUSES)


def test_every_table_with_updated_at_has_the_trigger(db: Session):
    """Fails when a new table uses Timestamps but its migration forgot the trigger."""
    with_column = {t.name for t in Base.metadata.sorted_tables if "updated_at" in t.columns}
    with_trigger = set(
        db.scalars(
            text(
                "SELECT event_object_table FROM information_schema.triggers "
                "WHERE trigger_name = 'set_updated_at' AND event_manipulation = 'UPDATE'"
            )
        )
    )
    assert with_column and with_column <= with_trigger, with_column - with_trigger


def test_check_constraints_match_between_models_and_database(db: Session):
    """Every CHECK the models declare exists in the database and vice versa, by name.
    `alembic check` ignores CHECK constraints, so a check removed from a model (or added to a
    migration only) would otherwise go unnoticed."""
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateTable

    dialect = postgresql.dialect()
    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=dialect))
        in_models = set(re.findall(r"CONSTRAINT (ck_\w+) CHECK", ddl))
        in_database = set(
            db.scalars(
                text(
                    "SELECT c.conname FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
                    "WHERE t.relname = :t AND c.contype = 'c'"
                ),
                {"t": table.name},
            )
        )
        assert in_models == in_database, f"{table.name}: models {in_models} vs db {in_database}"
