"""Scope resolution. Card M2-02 owns this file.

Keep `resolve_scope` a pure function (no database, no network) so it can be tested with tables
of cases. Callers load the active grants and pass them in.
"""

from pydantic import BaseModel, ConfigDict

from app.modules.policies.schemas import Grant
from app.shared.types import Pool, Principal


class Scope(BaseModel):
    model_config = ConfigDict(frozen=True)

    pools: frozenset[Pool]
    grant_ids: frozenset[str]  # grants that contributed, recorded in the audit log
    fingerprint: str  # stable hash of `pools`, stored on conversations (card M3-06)


def resolve_scope(principal: Principal, active_grants: list[Grant]) -> Scope:
    # TODO(M2-02): baseline (public everywhere; internal in own department; restricted in own
    # department for managers and owners) plus the pools each matching grant adds.
    raise NotImplementedError("Card M2-02")
