"""Card M3-07: the audit log is written in the caller's transaction and can never be changed.

The tests that matter most run as `capybara_app`, the role the API's login belongs to, and try
every way a compromised or buggy API could edit or erase the log.
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from alembic import command
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.db import check_app_login
from app.modules.audit import models
from app.modules.audit.schemas import EVENT_TYPES, AuditEventCreate, ChunkRef
from app.modules.audit.writer import record
from app.shared.logs import _request_id
from app.shared.types import Pool, Principal, Role, Sensitivity, SourceType
from tests.test_migrations import _check_values, scratch_engine  # noqa: F401 (fixture)

ENGINEER = Principal(
    user_id="u-1",
    username="eng.manager",
    display_name="Maya",
    department="engineering",
    role=Role.MANAGER,
)
ADMIN = ENGINEER.model_copy(update={"user_id": "u-9", "role": Role.MEMBER, "is_admin": True})
FINANCE_TICKETS = Pool(
    department="finance", source_type=SourceType.TICKETS, sensitivity=Sensitivity.INTERNAL
)
OWN_DOCS = Pool(
    department="engineering", source_type=SourceType.DOCS, sensitivity=Sensitivity.RESTRICTED
)
MARKETING_DOCS = Pool(
    department="marketing", source_type=SourceType.DOCS, sensitivity=Sensitivity.INTERNAL
)
GRANT = uuid.uuid4()


def _ref(pool: Pool) -> ChunkRef:
    return ChunkRef(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        department=pool.department,
        source_type=pool.source_type,
        sensitivity=pool.sensitivity,
    )


def _chat_event(**fields) -> AuditEventCreate:
    cited = _ref(FINANCE_TICKETS)
    values = {
        "question": "What's blocking Q4 vendor payments?",
        "pools_searched": [OWN_DOCS, FINANCE_TICKETS],
        "pools_denied": [MARKETING_DOCS],
        "pools_used": [FINANCE_TICKETS],
        "chunks_retrieved": [cited, _ref(OWN_DOCS)],
        "chunks_cited": [cited],
        "grant_ids": [GRANT],
    } | fields
    return AuditEventCreate.by(ENGINEER, "chat", **values)


def _count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(models.AuditEvent))


def _as_app(db: Session) -> None:
    """Run the rest of this transaction as the API's role (undone by the test's rollback)."""
    db.execute(text("SET LOCAL ROLE capybara_app"))


# What gets recorded


def test_record_stores_who_what_and_when(db: Session):
    event = record(db, _chat_event())

    assert event.id and event.at
    assert (event.user_id, event.user_department, event.user_role) == (
        "u-1",
        "engineering",
        "manager",
    )
    assert event.user_is_admin is False
    assert event.pools_used == [FINANCE_TICKETS]
    assert event.chunks_cited[0].department == "finance"
    assert event.chunks_cited[0].sensitivity is Sensitivity.INTERNAL
    assert event.grant_ids == [GRANT]
    assert event.request_id is None  # outside a request


def test_departments_come_from_pools_searched_and_used_not_denied(db: Session):
    # Marketing was only a planner's guess the user couldn't read: Marketing's owner must not
    # see this Engineering question.
    assert record(db, _chat_event()).departments == ["engineering", "finance"]


def test_explicit_departments_are_added(db: Session):
    # A Finance grant revoked by an admin concerns Finance, not the admin's own department.
    event = record(db, AuditEventCreate.by(ADMIN, "grant_revoked", departments=["finance"]))
    assert event.departments == ["finance"]
    assert event.user_is_admin is True


def test_record_keeps_the_request_id(db: Session):
    token = _request_id.set("req-123")
    try:
        assert record(db, _chat_event()).request_id == "req-123"
    finally:
        _request_id.reset(token)


def test_input_is_cleaned_or_refused():
    event = _chat_event(question="null\x00byte", departments=["  Finance "])
    assert event.question == "nullbyte"
    assert event.departments == ["finance"]
    for bad in [
        {"departments": ["fin|ance"]},
        {"departments": ["x" * 51]},
        {"grant_ids": ["not-a-uuid"]},
    ]:
        with pytest.raises(ValidationError):
            _chat_event(**bad)
    with pytest.raises(ValidationError):
        AuditEventCreate.by(ENGINEER, "hacked")


# Transactions


def test_the_event_is_saved_with_the_callers_work_or_not_at_all(db: Session):
    work = db.begin_nested()  # stands in for a request's transaction
    record(db, _chat_event())
    assert _count(db) == 1  # visible inside the transaction
    work.rollback()  # the request failed
    assert _count(db) == 0  # so its audit event is gone too


# Append-only, as the API's role


def test_the_api_role_can_record_and_read(db: Session):
    _as_app(db)
    assert db.scalar(text("SELECT current_user")) == "capybara_app"
    record(db, _chat_event())
    assert _count(db) == 1


def test_the_api_role_cannot_backdate_an_event(db: Session):
    _as_app(db)
    db.execute(
        text(
            "INSERT INTO audit_events (type, user_id, user_department, user_role, at) "
            "VALUES ('chat', 'u-1', 'engineering', 'member', '2001-01-01')"
        )
    )
    assert db.scalar(text("SELECT at FROM audit_events")) > datetime(2020, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE audit_events SET question = 'tampered'",
        "DELETE FROM audit_events",
        "TRUNCATE audit_events",
        "ALTER TABLE audit_events DISABLE TRIGGER ALL",
        "SET session_replication_role = replica",
        "ALTER TABLE audit_events ALTER COLUMN question TYPE text USING 'rewritten'",
        "CREATE OR REPLACE FUNCTION audit_events_append_only() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$",
        "DROP TABLE audit_events",
        "UPDATE alembic_version SET version_num = '0001'",
    ],
)
def test_the_api_role_cannot_edit_or_erase_the_log(db: Session, sql: str):
    record(db, _chat_event())
    _as_app(db)
    with pytest.raises(DBAPIError):
        db.execute(text(sql))
    db.rollback()


def test_the_api_role_can_still_write_data_tables(db: Session):
    _as_app(db)
    db.execute(text("INSERT INTO departments (id, name) VALUES ('legal', 'Legal')"))
    db.execute(text("UPDATE departments SET name = 'Legal & Compliance' WHERE id = 'legal'"))


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE audit_events SET question = 'tampered'",
        "DELETE FROM audit_events",
        "TRUNCATE audit_events",
    ],
)
def test_triggers_stop_even_the_owner_by_accident(db: Session, sql: str):
    record(db, _chat_event())
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text(sql))
    db.rollback()


def test_unknown_event_types_are_refused_by_the_database(db: Session):
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO audit_events (type, user_id, user_department, user_role) "
                "VALUES ('hacked', 'u-1', 'engineering', 'member')"
            )
        )
    db.rollback()


def test_event_types_match_the_database_check(db: Session):
    # Adding an event type in Python needs a migration changing ck_audit_events_type.
    assert _check_values(db, "audit_events", "type") == set(EVENT_TYPES)


def test_the_audit_api_is_still_card_m4_03(client):
    response = client.get("/api/v1/audit", headers={"X-Dev-User": "app.admin"})
    assert response.status_code == 501


# Second review: the privilege layer itself, not only the triggers


@pytest.mark.parametrize(
    ("privilege", "allowed"),
    [("SELECT", True), ("INSERT", True), ("UPDATE", False), ("DELETE", False), ("TRUNCATE", False)],
)
def test_the_api_role_has_exactly_select_and_insert_on_the_log(db: Session, privilege, allowed):
    granted = db.scalar(
        text("SELECT has_table_privilege('capybara_app', 'audit_events', :p)"), {"p": privilege}
    )
    assert granted is allowed


@pytest.mark.parametrize(
    "sql", ["UPDATE audit_events SET question = 'tampered'", "DELETE FROM audit_events"]
)
def test_the_api_role_is_refused_by_privileges_before_any_trigger(db: Session, sql: str):
    record(db, _chat_event())
    _as_app(db)
    with pytest.raises(DBAPIError, match="permission denied"):
        db.execute(text(sql))
    db.rollback()


def test_the_api_role_cannot_shadow_the_log_with_a_temporary_table(db: Session):
    _as_app(db)
    with pytest.raises(DBAPIError, match="permission denied"):
        db.execute(text("CREATE TEMP TABLE audit_events (LIKE public.audit_events)"))
    db.rollback()


def test_future_tables_with_serial_ids_work_for_the_api_role(db: Session):
    db.execute(text("CREATE TABLE future_things (id serial PRIMARY KEY, name text)"))
    _as_app(db)
    db.execute(text("INSERT INTO future_things (name) VALUES ('ok')"))
    assert db.scalar(text("SELECT count(*) FROM future_things")) == 1


def test_the_api_refuses_a_privileged_login(db: Session):
    with pytest.raises(RuntimeError, match="can change the audit log"):
        check_app_login(db.connection())  # the tests connect as the owner
    _as_app(db)
    with pytest.raises(RuntimeError, match="can change the audit log"):
        check_app_login(db.connection())  # SET ROLE doesn't hide the superuser login
    # A real limited login is accepted: see test_audit_contracts.py.


def test_downgrade_refuses_to_delete_audit_events(scratch_engine):  # noqa: F811 (fixture)
    engine, config = scratch_engine
    command.upgrade(config, "head")
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO audit_events (type, user_id, user_department, user_role) "
                "VALUES ('chat', 'u-1', 'engineering', 'member')"
            )
        )
    with pytest.raises(RuntimeError, match="allow_audit_loss"):
        command.downgrade(config, "0003")
    config.cmd_opts = SimpleNamespace(x=["allow_audit_loss=1"])
    command.downgrade(config, "0003")
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT to_regclass('audit_events')")) is None
