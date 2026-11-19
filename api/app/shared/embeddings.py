"""Text to vectors. Card M2-03 owns this file.

Used by ingestion (sources) to embed chunks and by retrieval to embed queries.
"""

from typing import Protocol


class Embedder(Protocol):
    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def get_embedder() -> Embedder:
    # TODO(M2-03): sentence-transformers all-MiniLM-L6-v2 on CPU, plus a deterministic
    # fake embedder for tests.
    raise NotImplementedError("Card M2-03")
