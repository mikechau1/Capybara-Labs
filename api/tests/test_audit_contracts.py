"""Card M3-07: what an audit event may contain, and which database logins the API refuses.

The login tests connect as real logins (not SET ROLE), because the check is about the login
itself: a session can always RESET ROLE back to whatever it logged in as.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.orm import Session

import app.db as app_db
from app.config import get_settings
from app.db import check_app_login
from app.main import create_app
from app.modules.audit import models
from app.modules.audit.schemas import AuditEventCreate
from app.modules.audit.writer import record
from app.shared.types import Pool, Principal, Role, Sensitivity, SourceType
from tests.conftest import API_ROOT
from tests.test_migrations import scratch_engine  # noqa: F401 (fixture)

ENGINEER = Principal(
    user_id="u-1",
    username="eng.manager",
    display_name="Maya",
    department="engineering",
    role=Role.MANAGER,
)


def _stored(db: Session, event: AuditEventCreate) -> models.AuditEvent:
    written = record(db, event)
    db.expire_all()
    return db.scalar(select(models.AuditEvent).where(models.AuditEvent.id == written.id))


# 1. detail is stored as JSON whatever it holds


def test_detail_with_uuids_datetimes_and_enums_is_recorded(db: Session):
    grant_id = uuid.uuid4()
    at = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
    event = AuditEventCreate.by(
        ENGINEER,
        "grant_revoked",
        detail={"grant_id": grant_id, "at": at, "role": Role.MEMBER, "ids": [grant_id]},
    )
    row = _stored(db, event)
    assert row.detail == {
        "grant_id": str(grant_id),
        "at": at.isoformat().replace("+00:00", "Z"),
        "role": "member",
        "ids": [str(grant_id)],
    }


# NUL characters: PostgreSQL text and JSONB can't hold them


def test_nul_characters_are_removed_from_detail_at_any_depth(db: Session):
    event = AuditEventCreate.by(
        ENGINEER,
        "access_request_created",
        detail={"reason": "need\x00it", "nested": [{"k\x00ey": "v\x00"}]},
    )
    assert event.detail == {"reason": "needit", "nested": [{"key": "v"}]}
    assert _stored(db, event).detail == event.detail


def test_a_user_id_with_a_nul_character_is_refused():
    with pytest.raises(ValidationError):
        AuditEventCreate.by(ENGINEER.model_copy(update={"user_id": "u\x001"}), "chat")


# Departments taken from pools are normalised like the explicit list


def test_pool_departments_are_normalised_like_explicit_ones(db: Session):
    pool = Pool(
        department=" Finance", source_type=SourceType.DOCS, sensitivity=Sensitivity.INTERNAL
    )
    event = AuditEventCreate.by(ENGINEER, "chat", pools_searched=[pool], pools_used=[pool])
    row = _stored(db, event)
    assert row.departments == ["finance"]
    assert row.pools_used[0]["department"] == "finance"


def test_a_pool_department_that_is_not_a_slug_is_refused():
    pool = Pool(
        department="fin|ance", source_type=SourceType.DOCS, sensitivity=Sensitivity.INTERNAL
    )
    for field in ("pools_searched", "pools_denied", "pools_used"):
        with pytest.raises(ValidationError):
            AuditEventCreate.by(ENGINEER, "chat", **{field: [pool]})


# 2. Which logins the API refuses


@pytest.fixture
def login(db_engine: Engine) -> Iterator:
    """Yields make(setup_sql) -> a connection as a new login that, like the real API login, is
    a member of capybara_app; setup_sql runs as the owner and may use {role}. Everything is
    undone afterwards."""
    owner = db_engine
    made: list[tuple[str, Engine, list[str]]] = []

    def make(*setup: str, undo: tuple[str, ...] = (), inherit: bool = True) -> Engine:
        role = f"t_login_{uuid.uuid4().hex[:10]}"
        with owner.begin() as conn:
            conn.execute(
                text(
                    f"CREATE ROLE {role} LOGIN PASSWORD 'pw' NOSUPERUSER "
                    f"{'INHERIT' if inherit else 'NOINHERIT'} IN ROLE capybara_app"
                )
            )
            for sql in setup:
                conn.execute(text(sql.format(role=role)))
        engine = create_engine(owner.url.set(username=role, password="pw"))
        made.append((role, engine, [u.format(role=role) for u in undo]))
        return engine

    try:
        yield make
    finally:
        for role, engine, undo in made:
            engine.dispose()
            with owner.begin() as conn:
                for sql in undo:
                    conn.execute(text(sql))
                conn.execute(text(f"DROP OWNED BY {role}"))
                conn.execute(text(f"DROP ROLE {role}"))


def _refused(engine: Engine) -> bool:
    with engine.connect() as conn:
        try:
            check_app_login(conn)
        except RuntimeError:
            return True
    return False


def test_a_login_with_only_the_app_role_is_accepted(login):
    assert not _refused(login())


def test_a_member_of_the_owner_role_is_refused(login):
    owner = "(SELECT tableowner FROM pg_tables WHERE tablename = 'audit_events')"
    engine = login(f"DO $$ BEGIN EXECUTE format('GRANT %I TO {{role}}', {owner}); END $$")
    assert _refused(engine)


def test_a_member_that_can_only_set_role_to_the_owner_is_refused(login):
    owner = "(SELECT tableowner FROM pg_tables WHERE tablename = 'audit_events')"
    engine = login(
        f"DO $$ BEGIN EXECUTE format('GRANT %I TO {{role}}', {owner}); END $$", inherit=False
    )
    assert _refused(engine)


def test_a_superuser_that_switched_role_is_refused(db_engine: Engine):
    # The tests connect as the owner, a superuser. SET ROLE makes current_user look limited.
    switched = create_engine(db_engine.url, connect_args={"options": "-c role=capybara_app"})
    try:
        with switched.connect() as conn:
            assert conn.scalar(text("SELECT current_user")) == "capybara_app"
        assert _refused(switched)
    finally:
        switched.dispose()


@pytest.mark.parametrize(
    "setup",
    [
        "GRANT pg_write_all_data TO {role}",
        "GRANT UPDATE ON audit_events TO {role}",
        "GRANT DELETE ON audit_events TO {role}",
        "GRANT TRUNCATE ON audit_events TO {role}",
        "GRANT TRIGGER ON audit_events TO {role}",  # could add a trigger that drops events
    ],
)
def test_a_login_that_can_change_the_log_by_privilege_is_refused(login, setup: str):
    assert _refused(login(setup))


def test_the_owner_of_a_trigger_function_is_refused(login):
    engine = login(
        "ALTER FUNCTION audit_events_stamp_time() OWNER TO {role}",
        undo=("ALTER FUNCTION audit_events_stamp_time() OWNER TO CURRENT_USER",),
    )
    assert _refused(engine)


def test_the_owner_of_the_schema_is_refused(login):
    engine = login(
        "ALTER SCHEMA public OWNER TO {role}",
        undo=("ALTER SCHEMA public OWNER TO pg_database_owner",),
    )
    assert _refused(engine)


# The check also runs at startup, and a refused login leaves no connection behind


@contextmanager
def _settings(monkeypatch, **env: str) -> Iterator[None]:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    app_db.get_engine.cache_clear()
    try:
        yield
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
        app_db.get_engine.cache_clear()


def test_a_refused_login_leaves_no_open_connection(monkeypatch, db_engine: Engine):
    created: list[Engine] = []
    real_create_engine = app_db.create_engine

    def tracking(*args, **kwargs):
        created.append(real_create_engine(*args, **kwargs))
        return created[-1]

    monkeypatch.setattr(app_db, "create_engine", tracking)
    url = db_engine.url.render_as_string(hide_password=False)
    with _settings(monkeypatch, ENVIRONMENT="development", DATABASE_URL=url):
        with pytest.raises(RuntimeError, match="can change the audit log"):
            app_db.get_engine()
    assert created and created[0].pool.checkedin() == 0


def test_the_api_refuses_to_start_with_a_privileged_login(monkeypatch, db_engine: Engine):
    url = db_engine.url.render_as_string(hide_password=False)
    with _settings(monkeypatch, ENVIRONMENT="development", AUTH_MODE="dev", DATABASE_URL=url):
        with pytest.raises(RuntimeError, match="can change the audit log"):
            with TestClient(create_app()):
                pass


# Migrations never fall back to the API's login


def test_migrations_without_an_owner_url_fail_clearly(monkeypatch):
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.attributes["keep_logging"] = True
    with _settings(
        monkeypatch,
        MIGRATION_DATABASE_URL="",
        DATABASE_URL="postgresql+psycopg://capybara_api:x@localhost:5432/capybara",
    ):
        with pytest.raises(RuntimeError, match="MIGRATION_DATABASE_URL"):
            command.upgrade(config, "head", sql=True)


def test_a_superuser_login_that_owns_nothing_is_refused(login):
    assert _refused(login("ALTER ROLE {role} SUPERUSER"))


def test_an_owner_that_revoked_its_own_rights_is_still_refused(login):
    # An owner can drop its own UPDATE/DELETE rights and still disable the triggers (or grant
    # the rights back), so ownership is checked on its own.
    engine = login(
        "ALTER TABLE audit_events OWNER TO {role}",
        "REVOKE UPDATE, DELETE, TRUNCATE, TRIGGER ON audit_events FROM {role}",
        undo=(
            "ALTER TABLE audit_events OWNER TO CURRENT_USER",
            "GRANT ALL ON audit_events TO CURRENT_USER",
        ),
    )
    assert _refused(engine)


def test_a_database_without_the_audit_log_is_refused(scratch_engine):  # noqa: F811 (fixture)
    engine, _ = scratch_engine  # an empty database: no migrations have run
    with engine.connect() as conn, pytest.raises(RuntimeError, match="run the migrations"):
        check_app_login(conn)


def test_starting_the_app_in_a_test_does_not_connect():
    with TestClient(create_app()) as client:  # runs the startup hook
        assert client.get("/health").status_code == 200


# Round 2: only the expected setup is accepted, whatever extra right a login has


_ON_THIS_DATABASE = (
    "DO $$ BEGIN EXECUTE 'GRANT {privilege} ON DATABASE ' || quote_ident(current_database())"
    " || ' TO {{role}}'; END $$"
)


@pytest.mark.parametrize(
    ("setup", "undo"),
    [
        (_ON_THIS_DATABASE.format(privilege="TEMPORARY"), ()),  # temp table shadows the log
        (_ON_THIS_DATABASE.format(privilege="CREATE"), ()),  # "$user" schema shadows the log
        ("GRANT CREATE ON SCHEMA public TO {role}", ()),  # e.g. its own clock_timestamp()
        ("GRANT pg_execute_server_program TO {role}", ()),  # COPY ... TO PROGRAM 'psql ...'
        ("GRANT pg_write_server_files TO {role}", ()),
        ("GRANT UPDATE (question) ON audit_events TO {role}", ()),  # column-level grant
        ("ALTER ROLE {role} CREATEDB", ()),
        ("ALTER ROLE {role} CREATEROLE", ()),
        ("ALTER ROLE {role} BYPASSRLS", ()),
        (
            "CREATE SCHEMA audit_shadow; CREATE TABLE audit_shadow.audit_events (id int)",
            ("DROP SCHEMA audit_shadow CASCADE",),
        ),
    ],
)
def test_any_right_beyond_the_app_role_is_refused(login, setup: str, undo: tuple[str, ...]):
    statements = (
        [part for part in setup.split("; ")] if setup.startswith("CREATE SCHEMA") else [setup]
    )
    assert _refused(login(*statements, undo=undo))


def test_the_refusal_names_what_is_wrong(login):
    engine = login("ALTER ROLE {role} CREATEDB", "GRANT pg_write_server_files TO {role}")
    with engine.connect() as conn, pytest.raises(RuntimeError) as error:
        check_app_login(conn)
    assert "has CREATEDB" in str(error.value) and "is also pg_write_server_files" in str(
        error.value
    )


def test_the_insert_time_ignores_a_clock_timestamp_on_the_search_path(db: Session):
    db.execute(text("CREATE SCHEMA fake_clock"))  # rolled back with the test
    db.execute(
        text(
            "CREATE FUNCTION fake_clock.clock_timestamp() RETURNS timestamptz LANGUAGE sql"
            " AS $$ SELECT timestamptz '2001-01-01' $$"
        )
    )
    db.execute(text("SET LOCAL search_path = fake_clock, pg_catalog, public"))
    assert db.scalar(text("SELECT clock_timestamp()")).year == 2001  # the trap is armed
    row = _stored(db, AuditEventCreate.by(ENGINEER, "chat"))
    assert row.at.year != 2001


# Lone surrogates, lengths, values that only become text when dumped


def test_lone_surrogates_are_replaced_so_the_request_does_not_fail(db: Session):
    event = AuditEventCreate.by(
        ENGINEER, "chat", question="a\ud800b", detail={"reason": "x\udfffy"}
    )
    row = _stored(db, event)
    assert row.question == "a?b" and row.detail == {"reason": "x?y"}


@pytest.mark.parametrize("user_id", ["u\ud800", "u" * 256])
def test_an_id_that_cannot_be_stored_exactly_is_refused(user_id):
    with pytest.raises(ValidationError):
        AuditEventCreate.by(ENGINEER.model_copy(update={"user_id": user_id}), "chat")


def test_values_that_become_text_only_when_dumped_are_cleaned_too(db: Session):
    from pydantic import BaseModel

    class Note(BaseModel):
        text: str

    event = AuditEventCreate.by(
        ENGINEER, "chat", detail={"raw": b"a\x00b", "note": Note.model_construct(text="c\x00d")}
    )
    assert _stored(db, event).detail == {"raw": "ab", "note": {"text": "cd"}}


# The downgrade guard


def test_downgrade_counts_an_event_that_is_being_written(scratch_engine):  # noqa: F811
    import threading

    engine, config = scratch_engine
    command.upgrade(config, "head")
    writer = engine.connect()
    transaction = writer.begin()
    writer.execute(
        text(
            "INSERT INTO audit_events (type, user_id, user_department, user_role)"
            " VALUES ('chat', 'u-1', 'engineering', 'member')"
        )
    )
    outcome: list[object] = []

    def downgrade() -> None:
        try:
            command.downgrade(config, "0003")
            outcome.append("dropped")
        except RuntimeError as exc:
            outcome.append(exc)

    other = threading.Thread(target=downgrade)
    other.start()
    other.join(1.0)  # waits for the open insert's lock
    transaction.commit()
    writer.close()
    other.join(30)
    assert outcome and isinstance(outcome[0], RuntimeError), outcome
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM audit_events")) == 1


def _offline_sql(config: Config, *args: str) -> str:
    import io

    buffer = io.StringIO()
    offline = Config(config.config_file_name, output_buffer=buffer)
    offline.set_main_option("script_location", config.get_main_option("script_location"))
    offline.attributes.update(config.attributes)
    getattr(command, args[0])(offline, args[1], sql=True)
    return buffer.getvalue()


def test_printed_migration_sql_is_valid_and_keeps_the_downgrade_guard(scratch_engine):  # noqa: F811
    engine, config = scratch_engine
    up = _offline_sql(config, "upgrade", "head")
    assert "%%" not in up and "quote_ident(current_database())" in up
    down = _offline_sql(config, "downgrade", "0004:0003")
    assert "LOCK TABLE audit_events" in down
    assert "audit_events holds events" in down.split("DROP TABLE audit_events")[0]


def test_the_test_environment_default_works_when_a_test_runs_alone():
    import os
    import subprocess
    import sys

    env = {k: v for k, v in os.environ.items() if k != "ENVIRONMENT"}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "tests/test_audit_contracts.py::test_starting_the_app_in_a_test_does_not_connect",
        ],
        cwd=API_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stdout[-2000:]
