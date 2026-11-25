"""Contracts later cards rely on (card M2-02): bad rows, blank values, the "any" sentinel,
and a Scope that can be hashed, logged and stored."""

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.policies import schemas, service
from app.modules.policies.schemas import Grant, GrantCreate
from app.modules.policies.scope import Scope, resolve_scope
from app.shared.types import Pool, Principal, Role, Sensitivity, SourceType
from tests import factories as make

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def _person(department: str = "engineering", user_id: str = "u-1") -> Principal:
    return Principal(
        user_id=user_id,
        username=user_id,
        display_name=user_id,
        department=department,
        role=Role.MEMBER,
    )


# 1. One bad row must not break scope resolution for everyone


def test_a_grant_row_that_fails_validation_is_skipped_not_fatal(db: Session, monkeypatch, caplog):
    make.department(db, "engineering")
    good = make.grant(db, "finance")
    bad = make.grant(db, "finance", source_type=SourceType.DOCS)
    original = Grant.model_validate

    def validate(row, **kwargs):
        if getattr(row, "id", None) == bad.id:
            return original({})  # raises ValidationError, like a row the schema rejects
        return original(row, **kwargs)

    monkeypatch.setattr(schemas.Grant, "model_validate", validate)
    caplog.set_level(logging.WARNING)
    grants = service.active_grants(db, datetime.now(UTC))
    assert [g.id for g in grants] == [good.id]
    assert any("malformed grant" in r.getMessage() for r in caplog.records)
    assert service.scope_for(db, _person()).allows(
        "finance", SourceType.TICKETS, Sensitivity.INTERNAL
    )


# 2. The database and the schema agree on what "blank" means


_BLANK_OR_PADDED = ["\t", "\n", " ", " u-1", "u-1 ", "u-1\n", ""]
_INSERTS = {
    "user_id_not_empty": "INSERT INTO grants (owning_department, grantee_user_id, max_sensitivity,"
    " created_by) VALUES ('finance', :v, 'internal', 'me')",
    "created_by_not_empty": "INSERT INTO grants (owning_department, grantee_min_role,"
    " max_sensitivity, created_by) VALUES ('finance', 'member', 'internal', :v)",
}


@pytest.mark.parametrize("constraint", sorted(_INSERTS))
@pytest.mark.parametrize("value", _BLANK_OR_PADDED)
def test_blank_or_padded_ids_are_refused_by_the_database(db: Session, constraint: str, value: str):
    make.department(db, "finance")
    # The exact constraint, so a failure for any other reason (a missing department) can't pass.
    with pytest.raises(IntegrityError, match=f"ck_grants_{constraint}"):
        db.execute(text(_INSERTS[constraint]), {"v": value})


@pytest.mark.parametrize("constraint", sorted(_INSERTS))
@pytest.mark.parametrize("value", ["u-1", "u 1", "a"])
def test_ordinary_ids_are_accepted_by_the_database(db: Session, constraint: str, value: str):
    make.department(db, "finance")
    db.execute(text(_INSERTS[constraint]), {"v": value})


@pytest.mark.parametrize("value", _BLANK_OR_PADDED)
def test_blank_or_padded_ids_are_refused_by_the_schema_not_trimmed(value: str):
    with pytest.raises(ValidationError):
        GrantCreate.model_validate(
            {"grantee_user_id": value, "source_type": "docs", "max_sensitivity": "internal"}
        )


# 3. "any" can never be a real department


def test_a_department_named_any_is_refused(db: Session):
    with pytest.raises(IntegrityError):
        db.execute(text("INSERT INTO departments (id, name) VALUES ('any', 'Any')"))
    db.rollback()


# 4. A Scope can be hashed, logged as JSON, and read back


def _granted_scope() -> Scope:
    grant = Grant(
        id=uuid.uuid4(),
        owning_department="finance",
        grantee_min_role=Role.MEMBER,
        source_type=SourceType.TICKETS,
        max_sensitivity=Sensitivity.INTERNAL,
        created_by="o",
        created_at=NOW - timedelta(days=1),
    )
    return resolve_scope(_person(), [grant], ["engineering", "finance"], NOW)


def test_a_scope_is_hashable():
    scope = _granted_scope()
    rebuilt = Scope(pools=set(scope.pools), pool_grants=dict(scope.pool_grants))
    assert rebuilt == scope and hash(rebuilt) == hash(scope)
    assert {scope: "cached"}[rebuilt] == "cached"
    assert hash(scope) != hash(Scope(pools=scope.pools))  # the grants are part of the key


def test_a_tampered_serialized_scope_is_refused():
    dumped = json.loads(_granted_scope().model_dump_json())
    for field, forged in [("fingerprint", "0" * 64), ("grant_ids", ["forged"])]:
        with pytest.raises(ValueError):
            Scope.model_validate({**dumped, field: forged})
    dumped["pools"] = dumped["pools"][1:]  # drop a pool, keep the old fingerprint
    with pytest.raises(ValueError):
        Scope.model_validate(dumped)


def test_scope_json_is_sorted_so_equal_scopes_serialize_identically():
    scope = _granted_scope()
    rebuilt = Scope(
        pools=list(reversed(sorted(scope.pools, key=str))), pool_grants=dict(scope.pool_grants)
    )
    assert rebuilt.model_dump_json() == scope.model_dump_json()


def test_a_scope_serializes_with_its_fingerprint_and_round_trips():
    scope = _granted_scope()
    dumped = json.loads(scope.model_dump_json())
    assert dumped["fingerprint"] == scope.fingerprint
    assert set(dumped["grant_ids"]) == set(scope.grant_ids)
    again = Scope.model_validate_json(scope.model_dump_json())
    assert again == scope and again.fingerprint == scope.fingerprint
    finance_tickets = Pool(
        department="finance", source_type=SourceType.TICKETS, sensitivity=Sensitivity.INTERNAL
    )
    assert again.grants_for([finance_tickets]) == scope.grants_for([finance_tickets]) != frozenset()


def _request(**fields) -> dict:
    base = {
        "grantee_department": "any",
        "grantee_min_role": "member",
        "source_type": "any",
        "max_sensitivity": "internal",
    }
    return {**base, **fields}


@pytest.mark.parametrize("value", [None, "text", 3, ["grantee_department", "any"]])
def test_a_grant_request_that_is_not_an_object_is_refused(value):
    with pytest.raises(ValidationError):
        GrantCreate.model_validate(value)


def test_a_validated_grant_request_can_be_validated_again():
    request = GrantCreate.model_validate(_request())
    assert GrantCreate.model_validate(request) == request


@pytest.mark.parametrize(
    ("ahead", "accepted"),
    [(timedelta(seconds=30), False), (timedelta(minutes=4), False), (timedelta(minutes=6), True)],
)
def test_a_grant_must_expire_with_a_margin_for_clock_skew(ahead, accepted):
    request = _request(
        max_sensitivity="restricted", expires_at=(datetime.now(UTC) + ahead).isoformat()
    )
    if accepted:
        assert GrantCreate.model_validate(request).expires_at is not None
    else:
        with pytest.raises(ValidationError, match="5 minutes"):
            GrantCreate.model_validate(request)


def test_a_pool_listed_twice_in_granted_is_refused():
    scope = _granted_scope()
    pool = next(iter(scope.pool_grants))
    with pytest.raises(ValueError, match="twice"):
        Scope(
            pools=scope.pools,
            granted=[{"pool": pool, "grant_ids": ["a"]}, {"pool": pool, "grant_ids": ["b"]}],
        )


def test_an_object_missing_breadth_fields_is_refused_not_widened():
    """from_attributes input must get the same "breadth is explicit" check as a dict, or a
    missing source_type would default to None, which means every source type."""
    from types import SimpleNamespace

    narrow_looking = SimpleNamespace(
        grantee_department="engineering", grantee_min_role="member", max_sensitivity="internal"
    )
    with pytest.raises(ValidationError):
        GrantCreate.model_validate(narrow_looking, from_attributes=True)


def test_scope_json_is_identical_in_every_process():
    """Sets iterate in a per-process order (string hashing is randomized), so unsorted JSON
    would differ between API workers for the same scope."""
    import os
    import subprocess
    import sys

    code = (
        "from tests.test_policies_contracts import _fixed_scope;"
        "print(_fixed_scope().model_dump_json())"
    )
    outputs = {
        subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        ).stdout
        for seed in ("1", "2", "3", "4")
    }
    assert len(outputs) == 1, outputs


def _fixed_scope() -> Scope:
    pools = [
        Pool(department=d, source_type=t, sensitivity=Sensitivity.PUBLIC)
        for d in ("finance", "hr", "it", "sales", "engineering")
        for t in SourceType
    ]
    return Scope(pools=pools, pool_grants={pools[0]: frozenset({"g-b", "g-a", "g-c"})})
