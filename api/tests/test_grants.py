"""Card M2-02: the grants table and loading a scope from the database."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.policies import models
from app.modules.policies.service import active_grants, scope_for
from app.shared.types import Principal, Role, Sensitivity, SourceType
from tests import factories as make

FUTURE = datetime.now(UTC) + timedelta(days=30)


def person(department: str, role: Role, user_id: str = "u-1") -> Principal:
    return Principal(
        user_id=user_id, username=user_id, display_name=user_id, department=department, role=role
    )


@pytest.mark.parametrize(
    "fields",
    [
        {"grantee_min_role": Role.MEMBER, "grantee_user_id": "u-1"},  # both kinds of grantee
        {"grantee_min_role": None},  # neither kind
        {"grantee_user_id": "u-1", "grantee_department": "engineering"},  # user + department
        {"max_sensitivity": Sensitivity.PUBLIC},  # public needs no grant
        {"max_sensitivity": Sensitivity.RESTRICTED},  # restricted without an expiry
    ],
)
def test_malformed_grants_are_refused_by_the_database(db: Session, fields: dict):
    make.department(db, "engineering")
    with pytest.raises(IntegrityError):
        make.grant(db, **fields)
    db.rollback()


def test_expiry_must_be_after_creation(db: Session):
    with pytest.raises(IntegrityError):
        make.grant(db, expires_at=datetime(2000, 1, 1, tzinfo=UTC))
    db.rollback()


def test_valid_grants_are_stored(db: Session):
    make.grant(db, grantee_department="engineering", grantee_min_role=Role.MANAGER)
    make.grant(db, grantee_user_id="u-42", source_type=SourceType.TICKETS)
    make.grant(db, max_sensitivity=Sensitivity.RESTRICTED, expires_at=FUTURE)
    assert db.scalar(text("SELECT count(*) FROM grants")) == 3


def test_active_grants_skip_revoked_and_expired(db: Session):
    now = datetime.now(UTC)
    keep = make.grant(db)
    revoked = make.grant(db)
    expiring = make.grant(db, expires_at=now + timedelta(hours=1))
    # The database's clock, as the revoke endpoint will use (revoked_at >= created_at).
    db.execute(
        update(models.Grant).where(models.Grant.id == revoked.id).values(revoked_at=func.now())
    )

    assert {g.id for g in active_grants(db, now)} == {keep.id, expiring.id}
    assert {g.id for g in active_grants(db, now + timedelta(hours=2))} == {keep.id}


def test_scope_for_uses_the_database(db: Session):
    # G1 from the design: Finance lets managers from any department read Finance tickets.
    make.department(db, "engineering")
    g1 = make.grant(db, "finance", source_type=SourceType.TICKETS, grantee_min_role=Role.MANAGER)

    manager = scope_for(db, person("engineering", Role.MANAGER))
    member = scope_for(db, person("engineering", Role.MEMBER))
    assert manager.allows("finance", SourceType.TICKETS, Sensitivity.INTERNAL)
    assert manager.grant_ids == {str(g1.id)}
    assert not member.allows("finance", SourceType.TICKETS, Sensitivity.INTERNAL)
    # Public pools of every department in the database, without any grant.
    assert member.allows("finance", SourceType.DOCS, Sensitivity.PUBLIC)


def test_revoking_takes_effect_on_the_next_call(db: Session):
    make.department(db, "engineering")
    g = make.grant(db, "finance")
    engineer = person("engineering", Role.MEMBER)
    assert scope_for(db, engineer).allows("finance", SourceType.DOCS, Sensitivity.INTERNAL)

    db.execute(
        update(models.Grant).where(models.Grant.id == g.id).values(revoked_at=datetime.now(UTC))
    )
    assert not scope_for(db, engineer).allows("finance", SourceType.DOCS, Sensitivity.INTERNAL)


_INSERT = (
    "INSERT INTO grants (owning_department, grantee_min_role, grantee_user_id, max_sensitivity,"
    " created_by) VALUES ('finance', {role}, {user}, 'internal', {by})"
)


@pytest.mark.parametrize(
    "values",
    [
        {"role": "'ceo'", "user": "NULL", "by": "'o'"},  # unknown role
        {"role": "NULL", "user": "'   '", "by": "'o'"},  # blank user id
        {"role": "'member'", "user": "NULL", "by": "'  '"},  # blank creator
    ],
)
def test_more_malformed_grant_rows_are_refused(db: Session, values: dict):
    make.department(db, "finance")
    with pytest.raises(IntegrityError):
        db.execute(text(_INSERT.format(**values)))
    db.rollback()


# Grants never change after creation, except one revoke (trigger in migration 0003).


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE grants SET source_type = NULL",  # widen in place
        "UPDATE grants SET expires_at = now() + interval '100 years'",
        "UPDATE grants SET max_sensitivity = 'restricted', expires_at = now() + interval '1 day'",
        "DELETE FROM grants",
    ],
)
def test_a_grant_cannot_be_changed_or_deleted(db: Session, sql: str):
    make.grant(db, source_type=SourceType.DOCS)
    with pytest.raises(IntegrityError, match="never"):
        db.execute(text(sql))
    db.rollback()


def test_a_revoke_cannot_be_undone_or_repeated(db: Session):
    make.grant(db)
    db.execute(text("UPDATE grants SET revoked_at = now()"))
    for sql in ["UPDATE grants SET revoked_at = NULL", "UPDATE grants SET revoked_at = now()"]:
        nested = db.begin_nested()
        with pytest.raises(IntegrityError, match="already revoked"):
            db.execute(text(sql))
        nested.rollback()


@pytest.mark.parametrize(
    "sent", ["created_at - interval '2 seconds'", "now() + interval '10 years'", "'2001-01-01'"]
)
def test_the_revoke_time_is_always_the_databases(db: Session, sent: str):
    make.grant(db)
    db.execute(text(f"UPDATE grants SET revoked_at = {sent}"))
    assert db.scalar(text("SELECT revoked_at = now() FROM grants"))


@pytest.mark.parametrize("sent", ["now() - interval '20 years'", "now() + interval '20 years'"])
def test_the_creation_time_is_always_the_databases(db: Session, sent: str):
    make.department(db, "finance")
    db.execute(
        text(
            "INSERT INTO grants (owning_department, grantee_min_role, max_sensitivity,"
            f" created_by, created_at) VALUES ('finance', 'member', 'internal', 'me', {sent})"
        )
    )
    assert db.scalar(text("SELECT created_at = now() FROM grants"))


def test_a_column_added_later_is_covered_by_the_immutability_trigger(db: Session):
    db.execute(text("ALTER TABLE grants ADD COLUMN note text"))  # rolled back with the test
    make.grant(db)
    with pytest.raises(IntegrityError, match="never changed"):
        db.execute(text("UPDATE grants SET revoked_at = now(), note = 'rewritten on revoke'"))
    db.rollback()


def test_a_guarded_revoke_of_a_revoked_grant_changes_nothing(db: Session):
    """The pattern documented for M4-01: a second revoke affects 0 rows instead of failing."""
    grant = make.grant(db)
    sql = text("UPDATE grants SET revoked_at = now() WHERE id = :id AND revoked_at IS NULL")
    assert db.execute(sql, {"id": grant.id}).rowcount == 1
    assert db.execute(sql, {"id": grant.id}).rowcount == 0


def test_scope_for_refuses_an_unknown_department(db: Session):
    from app.modules.policies.service import UnknownDepartment

    make.department(db, "finance")
    for department in ["Finance", "marketing"]:
        with pytest.raises(UnknownDepartment):
            scope_for(db, person(department, Role.MEMBER))


def test_empty_named_user_is_refused(db: Session):
    with pytest.raises(IntegrityError):
        make.grant(db, grantee_user_id="")
    db.rollback()


@pytest.mark.parametrize("bad_id", ["Engineering", "eng ops", "eng|ops", "-x", ""])
def test_department_ids_must_be_lowercase_slugs(db: Session, bad_id: str):
    with pytest.raises(IntegrityError):
        db.execute(text("INSERT INTO departments (id, name) VALUES (:id, 'x')"), {"id": bad_id})
    db.rollback()


def test_active_grants_for_a_user_skip_grants_meant_for_others(db: Session):
    now = datetime.now(UTC)
    make.department(db, "engineering")
    make.department(db, "marketing")
    mine = make.grant(db, grantee_user_id="u-1")
    my_department = make.grant(db, grantee_department="engineering")
    anyone = make.grant(db)
    make.grant(db, grantee_user_id="u-2")
    make.grant(db, grantee_department="marketing")

    engineer = person("engineering", Role.MEMBER, user_id="u-1")
    assert {g.id for g in active_grants(db, now, engineer)} == {
        mine.id,
        my_department.id,
        anyone.id,
    }
    assert len(active_grants(db, now)) == 5


def test_revoke_endpoint_rejects_an_id_that_is_not_a_uuid(client):
    response = client.post("/api/v1/grants/not-a-uuid/revoke", headers={"X-Dev-User": "fin.owner"})
    assert response.status_code == 422


@pytest.mark.parametrize(
    "sql", ["DELETE FROM grants", "TRUNCATE grants", "TRUNCATE grants CASCADE"]
)
def test_grants_are_never_deleted_or_truncated(db: Session, sql: str):
    make.grant(db)
    with pytest.raises(IntegrityError, match="never deleted"):
        db.execute(text(sql))
    db.rollback()


def test_a_revoke_in_a_transaction_older_than_the_grant_succeeds(db_engine):
    """now() is the transaction's start: a job that began before a grant was created must
    still be able to revoke it (the revoke time is moved up to the creation time)."""
    job = db_engine.connect()
    job.begin()
    job.execute(text("SELECT 1"))  # the job's transaction (and its now()) starts here
    try:
        with db_engine.begin() as c:
            c.execute(text("INSERT INTO departments (id, name) VALUES ('late-dept', 'Late')"))
            c.execute(
                text(
                    "INSERT INTO grants (owning_department, grantee_user_id, max_sensitivity,"
                    " created_by) VALUES ('late-dept', 'late-user', 'internal', 'owner')"
                )
            )
        job.execute(
            text(
                "UPDATE grants SET revoked_at = now()"
                " WHERE grantee_user_id = 'late-user' AND revoked_at IS NULL"
            )
        )
        job.commit()
        with db_engine.connect() as c:
            assert c.scalar(
                text(
                    "SELECT revoked_at = created_at FROM grants WHERE grantee_user_id = 'late-user'"
                )
            )
    finally:
        job.close()
        with db_engine.begin() as c:  # grants can't be deleted, except by the owner on purpose
            c.execute(text("ALTER TABLE grants DISABLE TRIGGER grants_only_revoke"))
            c.execute(text("DELETE FROM grants WHERE owning_department = 'late-dept'"))
            c.execute(text("ALTER TABLE grants ENABLE TRIGGER grants_only_revoke"))
            c.execute(text("DELETE FROM departments WHERE id = 'late-dept'"))


def test_a_generated_column_added_later_does_not_block_revokes(db: Session):
    db.execute(
        text(
            "ALTER TABLE grants ADD COLUMN label text"
            " GENERATED ALWAYS AS (created_by || '!') STORED"
        )
    )
    make.grant(db)
    db.execute(text("UPDATE grants SET revoked_at = now()"))
    assert db.scalar(text("SELECT revoked_at IS NOT NULL FROM grants"))
