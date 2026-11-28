"""Text to vectors. Card M2-03 owns this file.

Used by ingestion (card M2-04) to embed chunks and by retrieval (card M2-07) to embed queries.
Both must use the same embedder, or the vectors are not comparable: store `embedder.model_id`
with every chunk and have retrieval search only chunks with the current one.

    from app.shared.embeddings import get_embedder

    embedder = get_embedder()
    vectors = embedder.embed(["first chunk", "second chunk"])  # 384 numbers each
    embedder.count_tokens("some text")  # for the chunker; keep chunks <= MAX_INPUT_TOKENS

Two implementations, chosen with the EMBEDDER setting:
- "local" (default): sentence-transformers all-MiniLM-L6-v2, at a pinned revision, on the CPU.
  No API key, no network at run time; the Docker image downloads the model when it is built.
  Needs the `embeddings` extra (see docs/embeddings.md).
- "fake": a deterministic stand-in for tests and quick local work. Texts that share words get
  similar vectors, so search tests still behave sensibly, but it understands no meaning. Tests
  use it by default (tests/conftest.py).

Vectors are unit length, so cosine similarity equals the dot product; search with cosine
distance (`<=>`). Blank texts are refused: drop empty chunks before embedding.
"""

import hashlib
import logging
import math
import re
import threading
import unicodedata
from typing import Protocol

from app.config import get_settings

log = logging.getLogger(__name__)

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
# Exact model version. Changing it changes every vector: re-embed all chunks. Must match the
# revision in api/Dockerfile's model download step (tests/test_embeddings.py checks).
MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
EMBEDDING_DIMENSIONS = 384  # must match the chunks.embedding column (card M2-01)

# The model reads at most 256 word pieces including its two marker tokens, and silently drops
# the rest, so a chunk must stay at or under this many (about 190 English words).
MAX_INPUT_TOKENS = 254

# At most this many encodes run at once. More in parallel are no faster on a CPU but each holds
# its own working memory (40 simultaneous calls reached 3.2 GB in a review); extra callers wait.
_ENCODE_SLOTS = threading.BoundedSemaphore(2)
# Held by calls longer than one batch; see LocalEmbedder.embed.
_BULK = threading.Lock()


class Embedder(Protocol):
    dimensions: int
    model_id: str  # stored with each chunk; vectors from different model_ids don't mix

    def embed(self, texts: list[str]) -> list[list[float]]:
        """One unit-length vector of `dimensions` numbers per text, in the same order."""
        ...

    def count_tokens(self, text: str) -> int:
        """How much of the model's input limit `text` uses."""
        ...


def _refuse_blank(texts: list[str]) -> None:
    if isinstance(texts, str):
        # A string is a sequence too: it would be embedded one character at a time.
        raise TypeError("embed takes a list of texts; wrap a single text in a list")
    if any(not text.strip() for text in texts):
        raise ValueError("cannot embed blank text; drop empty chunks first")


class LocalEmbedder:
    """all-MiniLM-L6-v2 running on the CPU through sentence-transformers."""

    dimensions = EMBEDDING_DIMENSIONS
    model_id = f"{MODEL_NAME}@{MODEL_REVISION[:12]}"

    def __init__(self, batch_size: int = 32) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                'EMBEDDER=local needs the embeddings extra: pip install -e ".[embeddings]". '
                "Or set EMBEDDER=fake."
            ) from exc

        # The model is local and offline; these libraries otherwise log a warning per file.
        for noisy in ("huggingface_hub", "transformers", "sentence_transformers"):
            logging.getLogger(noisy).setLevel(logging.ERROR)

        self._model = SentenceTransformer(MODEL_NAME, revision=MODEL_REVISION, device="cpu")
        self._batch_size = batch_size
        actual = self._model.get_embedding_dimension()
        if actual != self.dimensions:
            raise RuntimeError(
                f"{MODEL_NAME} makes {actual}-number vectors, expected {self.dimensions}"
            )

    def count_tokens(self, text: str) -> int:
        return len(self._model.tokenizer.tokenize(text))

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        _refuse_blank(texts)
        too_long = [n for n in (self.count_tokens(t) for t in texts) if n > MAX_INPUT_TOKENS]
        if too_long:
            # Never log the text itself: it may be restricted document content.
            log.warning(
                "embedding input cut off at the model's limit",
                extra={"texts_cut": len(too_long), "longest_tokens": max(too_long)},
            )
        if len(texts) <= self._batch_size:
            with _ENCODE_SLOTS:
                return self._encode(texts)
        # A long call (ingestion) runs one batch at a time and only one such call at a time, so
        # at least one slot is always free for short calls (chat queries): they wait for at most
        # one batch, never for a whole document. Peak memory is still two encodes.
        vectors: list[list[float]] = []
        with _BULK:
            for start in range(0, len(texts), self._batch_size):
                with _ENCODE_SLOTS:
                    vectors.extend(self._encode(texts[start : start + self._batch_size]))
        return vectors

    def _encode(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode(
            texts,
            batch_size=self._batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        ).tolist()


_WORD = re.compile(r"[^\W_]+")


def _fake_stem(word: str) -> str:
    """Crude plural folding so "payments" and "payment" share a vector position."""
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


class FakeEmbedder:
    """Deterministic bag-of-words vectors: each word adds weight to two hashed positions.

    Same text, same vector, on every machine. Shared words (any language, plurals folded) make
    vectors closer. Distinct words occasionally collide on a position (about 1% of pairs), so
    don't write tests that depend on two unrelated words scoring exactly zero.
    """

    dimensions = EMBEDDING_DIMENSIONS
    model_id = "fake-v2"

    def count_tokens(self, text: str) -> int:
        """An estimate of the real tokenizer's count that errs high, so chunker tests split no
        later than the real model would: 1.3 pieces per word, one per punctuation mark and per
        CJK character, plus 10%. On this repo's own docs it came out 1.03-1.38x the real count
        (measured 2026-11-22); plain prose is about 1.15 real pieces per word, text with paths,
        numbers or code much more, which is why punctuation counts separately."""
        words = len(_WORD.findall(text))
        punctuation = sum(1 for ch in text if not ch.isspace() and not ch.isalnum())
        wide = sum(1 for ch in text if unicodedata.east_asian_width(ch) in ("W", "F"))
        return math.ceil(1.1 * (1.3 * words + punctuation + wide))

    def embed(self, texts: list[str]) -> list[list[float]]:
        _refuse_blank(texts)
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for word in _WORD.findall(text.casefold()):
            digest = hashlib.sha256(_fake_stem(word).encode()).digest()
            for offset in (0, 4):
                index = int.from_bytes(digest[offset : offset + 4], "big") % self.dimensions
                vector[index] += 1.0 if digest[offset + 8] % 2 else -1.0
        length = math.sqrt(sum(v * v for v in vector))
        if length == 0:  # only punctuation; still return a unit vector
            vector[0] = 1.0
            return vector
        return [v / length for v in vector]


_embedder: Embedder | None = None
_lock = threading.Lock()


def get_embedder() -> Embedder:
    """The embedder chosen by EMBEDDER, created once per process. The local model takes about
    5 seconds and 450 MB to load (see docs/embeddings.md); the lock makes simultaneous first
    requests wait for one load instead of each loading a copy."""
    global _embedder
    if _embedder is None:
        with _lock:
            if _embedder is None:
                _embedder = FakeEmbedder() if get_settings().embedder == "fake" else LocalEmbedder()
                # Say which embedder is active: vectors from different ones must never mix.
                log.info("embedder ready", extra={"model_id": _embedder.model_id})
    return _embedder


def reset_embedder() -> None:
    """Forget the cached embedder (tests use this after changing EMBEDDER)."""
    global _embedder
    with _lock:
        _embedder = None
