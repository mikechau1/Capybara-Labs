"""Card M2-02: scope resolution rules, as pure table-driven tests (no database)."""

import ast
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.modules.policies.schemas import Grant
from app.modules.policies.scope import Scope, resolve_scope
from app.shared.types import Pool, Principal, Role, Sensitivity, SourceType

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
DEPARTMENTS = ["engineering", "finance"]
# sha256 of the sorted "department|type|sensitivity" lines of a Finance member's baseline:
# public everywhere plus Finance internal. Computed independently of scope.py.
FINANCE_MEMBER_FINGERPRINT = "ad0530598ac29c476a44b064ba02a4f3de69daa1953d7899ac901321b841eafb"
PUB, INT, RES = Sensitivity.PUBLIC, Sensitivity.INTERNAL, Sensitivity.RESTRICTED
DOCS, TICKETS, DISCORD = SourceType.DOCS, SourceType.TICKETS, SourceType.DISCORD


def person(department: str, role: Role, user_id: str | None = None, admin: bool = False):
    user_id = user_id or f"{department}-{role}"
    return Principal(
        user_id=user_id,
        username=user_id,
        display_name=user_id,
        department=department,
        role=role,
        is_admin=admin,
    )


def grant(owning: str, max_sensitivity: Sensitivity = INT, **fields) -> Grant:
    if "grantee_user_id" not in fields:
        fields.setdefault("grantee_min_role", Role.MEMBER)
    return Grant(
        id=uuid.uuid4(),
        owning_department=owning,
        max_sensitivity=max_sensitivity,
        created_by="owner",
        created_at=NOW - timedelta(days=30),
        **fields,
    )


def pools(department: str, types=SourceType, levels=(PUB, INT, RES)) -> set[Pool]:
    return {
        Pool(department=department, source_type=t, sensitivity=s) for t in types for s in levels
    }


def scope(principal: Principal, *grants: Grant, now: datetime = NOW):
    return resolve_scope(principal, list(grants), DEPARTMENTS, now)


# Baseline


@pytest.mark.parametrize(
    ("principal", "expected"),
    [
        (
            person("engineering", Role.MEMBER),
            pools("engineering", levels=(PUB, INT)) | pools("finance", levels=(PUB,)),
        ),
        (
            person("engineering", Role.MANAGER),
            pools("engineering") | pools("finance", levels=(PUB,)),
        ),
        (person("engineering", Role.OWNER), pools("engineering") | pools("finance", levels=(PUB,))),
        (
            person("finance", Role.MEMBER),
            pools("finance", levels=(PUB, INT)) | pools("engineering", levels=(PUB,)),
        ),
        # The app-admin flag gives no data access.
        (
            person("engineering", Role.MEMBER, admin=True),
            pools("engineering", levels=(PUB, INT)) | pools("finance", levels=(PUB,)),
        ),
    ],
)
def test_baseline(principal, expected):
    result = scope(principal)
    assert result.pools == expected
    assert result.grant_ids == frozenset()


# The worked example from the design:
#   G1: Finance lets managers from any department read Finance tickets up to internal.
#   G2: Engineering lets all Finance members read Engineering docs up to internal.

G1 = grant("finance", INT, source_type=TICKETS, grantee_min_role=Role.MANAGER)
G2 = grant("engineering", INT, source_type=DOCS, grantee_department="finance")


@pytest.mark.parametrize(
    ("principal", "added", "grant_ids"),
    [
        (person("engineering", Role.MEMBER), set(), set()),
        (person("engineering", Role.MANAGER), pools("finance", [TICKETS], (INT,)), {G1.id}),
        (person("finance", Role.MEMBER), pools("engineering", [DOCS], (INT,)), {G2.id}),
        # G1 matches the Finance owner but adds nothing new, so it is not recorded.
        (person("finance", Role.OWNER), pools("engineering", [DOCS], (INT,)), {G2.id}),
    ],
)
def test_worked_example(principal, added, grant_ids):
    assert scope(principal, G1, G2).pools - scope(principal).pools == added
    assert scope(principal, G1, G2).grant_ids == {str(i) for i in grant_ids}


def test_engineering_manager_gets_finance_internal_tickets_but_not_restricted():
    result = scope(person("engineering", Role.MANAGER), G1, G2)
    assert result.allows("finance", TICKETS, INT)
    assert not result.allows("finance", TICKETS, RES)
    assert not result.allows("finance", DOCS, INT)


# Grant matching


@pytest.mark.parametrize(
    ("role", "matches"), [(Role.MEMBER, False), (Role.MANAGER, True), (Role.OWNER, True)]
)
def test_minimum_role(role, matches):
    g = grant("finance", INT, grantee_min_role=Role.MANAGER)
    assert scope(person("engineering", role), g).allows("finance", DOCS, INT) is matches


def test_grantee_department_must_match():
    g = grant("finance", INT, grantee_department="marketing")
    assert not scope(person("engineering", Role.OWNER), g).allows("finance", DOCS, INT)


def test_any_department_and_any_source_type():
    g = grant("finance", INT)  # grantee_department None, source_type None
    added = (
        scope(person("engineering", Role.MEMBER), g).pools
        - scope(person("engineering", Role.MEMBER)).pools
    )
    assert added == pools("finance", levels=(INT,))


def test_restricted_grant_covers_every_level_below():
    g = grant("finance", RES, source_type=TICKETS, expires_at=NOW + timedelta(days=7))
    result = scope(person("engineering", Role.MEMBER), g)
    assert {result.allows("finance", TICKETS, s) for s in Sensitivity} == {True}


def test_named_user_grant_matches_only_that_user():
    g = grant("finance", INT, grantee_user_id="u-42")
    assert scope(person("engineering", Role.MEMBER, user_id="u-42"), g).allows("finance", DOCS, INT)
    assert not scope(person("engineering", Role.OWNER, user_id="u-43"), g).allows(
        "finance", DOCS, INT
    )


def test_revoked_grant_is_ignored():
    g = grant("finance", INT, revoked_at=NOW - timedelta(hours=1))
    assert not scope(person("engineering", Role.MEMBER), g).allows("finance", DOCS, INT)


@pytest.mark.parametrize(
    ("expires_at", "active"),
    [
        (NOW + timedelta(seconds=1), True),
        (NOW, False),
        (NOW - timedelta(days=1), False),
        (None, True),
    ],
)
def test_expiry(expires_at, active):
    g = grant("finance", INT, expires_at=expires_at)
    assert scope(person("engineering", Role.MEMBER), g).allows("finance", DOCS, INT) is active


# Fingerprint and inputs


def test_fingerprint_depends_only_on_the_pools():
    eng = person("engineering", Role.MANAGER)
    assert scope(eng, G1, G2).fingerprint == scope(eng, G2, G1).fingerprint
    assert scope(eng, G1).fingerprint == scope(eng, G1, G2).fingerprint  # G2 adds nothing here
    assert scope(eng).fingerprint != scope(eng, G1).fingerprint
    assert len(scope(eng).fingerprint) == 64


def test_naive_time_is_refused():
    with pytest.raises(ValueError):
        resolve_scope(person("finance", Role.MEMBER), [], DEPARTMENTS, datetime(2026, 1, 1))


def test_scope_module_has_no_database_or_network_imports():
    source = Path(__file__).resolve().parents[1] / "app/modules/policies/scope.py"
    imported = set()
    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {"sqlalchemy", "psycopg", "httpx", "requests", "fastapi"}


# Contracts later cards rely on (from the review of the first version)


def test_malformed_grants_are_refused_when_built():
    from pydantic import ValidationError

    base = {
        "id": uuid.uuid4(),
        "owning_department": "finance",
        "created_by": "o",
        "created_at": NOW,
    }
    for bad in [
        {"max_sensitivity": INT},  # no grantee at all
        {"max_sensitivity": INT, "grantee_min_role": Role.MEMBER, "grantee_user_id": "u"},
        {"max_sensitivity": INT, "grantee_user_id": "u", "grantee_department": "finance"},
        {"max_sensitivity": PUB, "grantee_min_role": Role.MEMBER},
        {"max_sensitivity": RES, "grantee_min_role": Role.MEMBER},  # restricted, no expiry
        {"max_sensitivity": INT, "grantee_user_id": ""},
        {
            "max_sensitivity": INT,
            "grantee_min_role": Role.MEMBER,
            "expires_at": datetime(2030, 1, 1),
        },
    ]:
        with pytest.raises(ValidationError):
            Grant(**base, **bad)


def test_a_grant_without_a_grantee_matches_nobody():
    # Even if one is built without validation, it must fail closed, never mean "everyone".
    g = Grant.model_construct(
        id=uuid.uuid4(),
        owning_department="finance",
        max_sensitivity=RES,
        grantee_department=None,
        grantee_min_role=None,
        grantee_user_id=None,
        source_type=None,
        expires_at=None,
        created_by="o",
        created_at=NOW,
        revoked_at=None,
    )
    assert not scope(person("engineering", Role.OWNER), g).allows("finance", DOCS, RES)


def test_overlapping_grants_are_all_recorded_whatever_the_order():
    g1 = grant("finance", INT, source_type=TICKETS)
    g2 = grant("finance", INT)  # also covers finance tickets
    engineer = person("engineering", Role.MEMBER)
    for order in [(g1, g2), (g2, g1)]:
        result = scope(engineer, *order)
        tickets = Pool(department="finance", source_type=TICKETS, sensitivity=INT)
        assert result.pool_grants[tickets] == {str(g1.id), str(g2.id)}
        assert result.grant_ids == {str(g1.id), str(g2.id)}


def test_grants_for_names_only_the_grants_behind_the_pools_used():
    engineer = person("engineering", Role.MANAGER)
    result = scope(engineer, G1, G2)
    finance_tickets = Pool(department="finance", source_type=TICKETS, sensitivity=INT)
    own_docs = Pool(department="engineering", source_type=DOCS, sensitivity=RES)
    assert result.grants_for([finance_tickets, own_docs]) == {str(G1.id)}
    assert result.grants_for([own_docs]) == frozenset()  # baseline needs no grant


def test_fingerprint_is_the_same_in_every_process():
    # Stored on conversations (card M3-06), so it must not depend on hash seeds or set order.
    # If this value changes, every open conversation closes on deploy: change it deliberately.
    result = scope(person("finance", Role.MEMBER))
    assert result.fingerprint == FINANCE_MEMBER_FINGERPRINT


# Second review: inputs that must never widen access


def test_grant_requests_must_state_breadth_explicitly():
    from pydantic import ValidationError

    from app.modules.policies.schemas import GrantCreate

    base = {"grantee_min_role": "member", "max_sensitivity": "internal"}
    for missing in [base, base | {"source_type": None}, base | {"source_type": "any"}]:
        with pytest.raises(ValidationError):  # no grantee_department and/or no source_type
            GrantCreate.model_validate(missing)
    explicit = GrantCreate.model_validate(
        base | {"grantee_department": "any", "source_type": "any"}
    )
    assert (explicit.grantee_department, explicit.source_type) == (None, None)
    named = GrantCreate.model_validate(
        {"grantee_user_id": "u-1", "max_sensitivity": "internal", "source_type": "docs"}
    )
    assert named.grantee_user_id == "u-1"
    with pytest.raises(ValidationError):
        GrantCreate.model_validate(
            base
            | {
                "grantee_department": "any",
                "source_type": "any",
                "expires_at": "2001-01-01T00:00:00Z",
            }
        )


def test_blank_ids_and_backwards_expiry_are_refused():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        grant("finance", INT, grantee_user_id="   ")
    with pytest.raises(ValidationError):
        grant("finance", INT, expires_at=NOW - timedelta(days=60))  # before created_at


@pytest.mark.parametrize(
    "fields",
    [
        {"max_sensitivity": RES, "expires_at": None},  # restricted without expiry
        {"source_type": ""},  # empty, not "any"
        {"id": "NOT-A-UUID"},
        {"grantee_min_role": None},  # no grantee
    ],
)
def test_malformed_grants_are_skipped_never_widening_access(fields, caplog):
    values = {
        "id": uuid.uuid4(),
        "owning_department": "finance",
        "grantee_department": None,
        "grantee_min_role": Role.MEMBER,
        "grantee_user_id": None,
        "source_type": DOCS,
        "max_sensitivity": INT,
        "expires_at": None,
        "created_by": "o",
        "created_at": NOW - timedelta(days=1),
        "revoked_at": None,
    } | fields
    bad = Grant.model_construct(**values)
    engineer = person("engineering", Role.OWNER)
    assert scope(engineer, bad).pools == scope(engineer).pools
    assert any("malformed grant" in r.getMessage() for r in caplog.records)


def test_scope_cannot_be_tampered_with():
    result = scope(person("engineering", Role.MANAGER), G1)
    pool = next(iter(result.pool_grants))
    with pytest.raises(TypeError):
        result.pool_grants[pool] = frozenset({"forged"})  # read-only
    outside = Pool(department="hr", source_type=DOCS, sensitivity=RES)
    with pytest.raises(ValueError):
        Scope(pools=result.pools, pool_grants={outside: frozenset({"g"})})
    # The fingerprint is computed, so it always matches the pools.
    assert Scope(pools=result.pools).fingerprint == result.fingerprint
