"""Scope resolution: which pools a user may read. Card M2-02 owns this file.

`resolve_scope` is a pure function (no database, no network, no clock) so it can be tested
with tables of cases. `service.scope_for` loads what it needs and calls it.

Rules, applied fresh on every question:

1. Baseline, without any grant:
   - public pools of every department;
   - internal pools of the user's own department;
   - restricted pools of the user's own department, for managers and owners.
2. A grant matches when it is not revoked, not expired, and either names this user, or its
   grantee department is the user's (or any) and the user's role is at or above its minimum.
   The role compared is the one the user holds in their own department.
3. A matching grant adds its owning department's pools for its source type (or every type) at
   every sensitivity up to its maximum.
4. The scope is the union. Grants only add; there are no deny rules. The app-admin flag adds
   nothing: admins run the system but get no data access from it.

A pool is (department, source type, sensitivity), and retrieval (card M2-07) puts exactly these
triples in its SQL WHERE clause.

The fingerprint covers every pool, including other departments' public ones, so adding a
department changes everyone's fingerprint and closes their open conversations (card M3-06).
That is intended: it is rare, and safe in the right direction.
"""

import hashlib
import logging
from collections.abc import Iterable, Mapping
from datetime import datetime
from types import MappingProxyType
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    computed_field,
    field_serializer,
    model_validator,
)

from app.modules.policies.schemas import Grant
from app.shared.types import (
    ROLE_RANK,
    SENSITIVITY_RANK,
    Pool,
    Principal,
    Role,
    Sensitivity,
    SourceType,
)

log = logging.getLogger(__name__)


def _pool_key(pool: Pool) -> tuple[str, str, str]:
    return (pool.department, pool.source_type.value, pool.sensitivity.value)


class PoolGrants(BaseModel):
    """One pool a grant gave beyond the baseline, with the ids of every grant that gives it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pool: Pool
    grant_ids: frozenset[str] = Field(min_length=1)

    @field_serializer("grant_ids")
    def _sorted_ids(self, ids: frozenset[str]) -> list[str]:
        return sorted(ids)


class Scope(BaseModel):
    """A user's readable pools.

    Immutable, hashable (usable as a cache key) and serializable: `model_dump_json()` writes
    sorted lists plus the computed `fingerprint` and `grant_ids`, and `model_validate_json()`
    reads that back into an equal Scope. A stored fingerprint or grant list that no longer
    matches the pools is refused rather than trusted, since both are always recomputed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    pools: frozenset[Pool]
    # The pools grants gave beyond the baseline. Audit (card M3-07) records
    # grants_for(the pools an answer actually used). Read it through `pool_grants`.
    granted: frozenset[PoolGrants] = frozenset()

    @model_validator(mode="wrap")
    @classmethod
    def _accept_mapping_and_verify_computed(cls, data: Any, handler: Any) -> "Scope":
        stored_fingerprint = stored_grant_ids = None
        if isinstance(data, dict):
            data = dict(data)
            if "pool_grants" in data:
                if "granted" in data:
                    raise ValueError("give pool_grants or granted, not both")
                if not isinstance(data["pool_grants"], Mapping):
                    raise ValueError("pool_grants must map pools to grant ids")
                data["granted"] = [
                    {"pool": pool, "grant_ids": ids}
                    for pool, ids in data.pop("pool_grants").items()
                ]
            # Computed fields from a serialized Scope: never trusted, but they must still match.
            stored_fingerprint = data.pop("fingerprint", None)
            stored_grant_ids = data.pop("grant_ids", None)
        scope = handler(data)
        if stored_fingerprint is not None and stored_fingerprint != scope.fingerprint:
            raise ValueError("fingerprint does not match the pools")
        if stored_grant_ids is not None and set(stored_grant_ids) != scope.grant_ids:
            raise ValueError("grant_ids do not match the granted pools")
        return scope

    @model_validator(mode="after")
    def _consistent(self) -> "Scope":
        named = [g.pool for g in self.granted]
        if len(named) != len(set(named)):
            raise ValueError("a pool is listed twice in granted")
        if not set(named) <= self.pools:
            raise ValueError("pool_grants names pools outside the scope")
        return self

    @field_serializer("pools")
    def _sorted_pools(self, pools: frozenset[Pool]) -> list[dict[str, str]]:
        return [p.model_dump(mode="json") for p in sorted(pools, key=_pool_key)]

    @field_serializer("granted")
    def _sorted_granted(self, granted: frozenset[PoolGrants]) -> list[dict[str, Any]]:
        return [g.model_dump(mode="json") for g in sorted(granted, key=lambda g: _pool_key(g.pool))]

    @property
    def pool_grants(self) -> Mapping[Pool, frozenset[str]]:
        """Read-only: for each pool a grant gave beyond the baseline, the grants that give it."""
        return MappingProxyType({g.pool: g.grant_ids for g in self.granted})

    @computed_field  # type: ignore[prop-decorator]
    @property
    def grant_ids(self) -> frozenset[str]:
        """Every grant that gave access beyond the baseline."""
        return frozenset().union(*(g.grant_ids for g in self.granted))

    @field_serializer("grant_ids")
    def _sorted_grant_ids(self, ids: frozenset[str]) -> list[str]:
        return sorted(ids)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def fingerprint(self) -> str:
        """Stable hash of `pools`, stored on conversations (card M3-06)."""
        return fingerprint(self.pools)

    def allows(self, department: str, source_type: SourceType, sensitivity: Sensitivity) -> bool:
        return (
            Pool(department=department, source_type=source_type, sensitivity=sensitivity)
            in self.pools
        )

    def grants_for(self, pools: Iterable[Pool]) -> frozenset[str]:
        """The grants that gave access to any of `pools` (empty if all are baseline)."""
        mapping = self.pool_grants
        return frozenset().union(*(mapping.get(p, frozenset()) for p in pools))


def _pools(
    department: str, source_types: Iterable[SourceType], max_sensitivity: Sensitivity
) -> set[Pool]:
    levels = [s for s in Sensitivity if SENSITIVITY_RANK[s] <= SENSITIVITY_RANK[max_sensitivity]]
    return {
        Pool(department=department, source_type=t, sensitivity=s)
        for t in source_types
        for s in levels
    }


def baseline_pools(principal: Principal, departments: Iterable[str]) -> set[Pool]:
    pools: set[Pool] = set()
    for department in departments:
        pools |= _pools(department, SourceType, Sensitivity.PUBLIC)
    own_level = (
        Sensitivity.RESTRICTED
        if ROLE_RANK[principal.role] >= ROLE_RANK[Role.MANAGER]
        else Sensitivity.INTERNAL
    )
    pools |= _pools(principal.department, SourceType, own_level)
    return pools


def grant_is_active(grant: Grant, now: datetime) -> bool:
    if grant.revoked_at is not None:
        return False
    if grant.expires_at is None:
        # A restricted grant must expire; one that doesn't is malformed. Fail closed.
        return grant.max_sensitivity != Sensitivity.RESTRICTED
    return grant.expires_at > now


def grant_matches(grant: Grant, principal: Principal) -> bool:
    if grant.grantee_user_id is not None:
        return grant.grantee_user_id == principal.user_id
    if grant.grantee_min_role is None:
        return False  # malformed: no grantee at all. Fail closed.
    if grant.grantee_department is not None and grant.grantee_department != principal.department:
        return False
    return ROLE_RANK[principal.role] >= ROLE_RANK[grant.grantee_min_role]


def grant_pools(grant: Grant) -> set[Pool]:
    source_types = [grant.source_type] if grant.source_type is not None else list(SourceType)
    return _pools(grant.owning_department, source_types, grant.max_sensitivity)


def fingerprint(pools: Iterable[Pool]) -> str:
    keys = sorted(f"{p.department}|{p.source_type.value}|{p.sensitivity.value}" for p in pools)
    return hashlib.sha256("\n".join(keys).encode()).hexdigest()


def resolve_scope(
    principal: Principal, grants: Iterable[Grant], departments: Iterable[str], now: datetime
) -> Scope:
    """`departments` is every department id (for public pools). `grants` may include inactive
    ones; they are filtered here. `now` must be timezone-aware."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    baseline = baseline_pools(principal, departments)
    pools = set(baseline)
    pool_grants: dict[Pool, set[str]] = {}
    for grant in filter(None, map(_checked, grants)):
        if not (grant_is_active(grant, now) and grant_matches(grant, principal)):
            continue
        added = grant_pools(grant)
        for pool in added - baseline:  # compared with the baseline, so order never matters
            pool_grants.setdefault(pool, set()).add(str(grant.id))
        pools |= added
    return Scope(pools=frozenset(pools), pool_grants=pool_grants)


def _checked(grant: Grant) -> Grant | None:
    """The grant, re-validated; None (skipped, logged) if it breaks the rules. Grants built
    without validation (model_construct) or loaded from a bad row can never widen a scope, and
    one bad row never blocks scope resolution for everyone else."""
    try:
        return Grant.model_validate(grant.model_dump(warnings=False))
    except ValidationError:
        log.warning(
            "ignoring a malformed grant", extra={"grant_id": str(getattr(grant, "id", None))}
        )
        return None
