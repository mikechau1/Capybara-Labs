"""Hybrid search with the access filter. Card M2-07 owns this file."""

from pydantic import BaseModel

from app.modules.policies.scope import Scope
from app.shared.types import Pool, Sensitivity, SourceType


class RetrievedChunk(BaseModel):
    chunk_id: str
    text: str
    document_title: str
    department: str
    source_type: SourceType
    sensitivity: Sensitivity
    link: str


def search(
    scope: Scope, query: str, target_pools: set[Pool] | None = None, k: int = 10
) -> list[RetrievedChunk]:
    # TODO(M2-07): vector similarity + full-text, combined by reciprocal rank fusion, with the
    # scope in the WHERE clause. target_pools narrows the search; it can never widen the scope.
    raise NotImplementedError("Card M2-07")
