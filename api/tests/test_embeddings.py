"""Card M2-03: the embedding service.

The fake embedder is always tested. The real model is tested only where the `embeddings`
extra is installed (the Docker image, or `pip install -e ".[embeddings]"`); elsewhere those
tests are skipped, so CI and teammates without PyTorch still run everything else.
"""

import logging
import math
import re
import threading
import time
import tomllib
from pathlib import Path

import pytest

from app.config import Settings, get_settings
from app.shared import embeddings
from app.shared.embeddings import (
    EMBEDDING_DIMENSIONS,
    MAX_INPUT_TOKENS,
    MODEL_REVISION,
    FakeEmbedder,
    LocalEmbedder,
)

API = Path(__file__).resolve().parents[1]


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))  # vectors are unit length


def _is_unit(vector: list[float]) -> bool:
    return math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0, rel_tol=1e-5)


@pytest.fixture
def use_embedder(monkeypatch):
    """Point get_embedder() at a given EMBEDDER setting, with fresh caches."""

    def choose(kind: str) -> None:
        monkeypatch.setenv("EMBEDDER", kind)
        get_settings.cache_clear()
        embeddings.reset_embedder()

    return choose


def test_dimensions_match_the_chunks_column():
    # The chunks.embedding column (card M2-01) is vector(384). Once both cards are merged,
    # compare with app.modules.sources.models.EMBEDDING_DIMENSIONS instead of the number.
    assert EMBEDDING_DIMENSIONS == 384


# Reproducibility: the same build always produces the same vectors


def _dockerfile() -> str:
    path = API / "Dockerfile"
    if not path.exists():
        pytest.skip("checks the repo; the image does not contain its own Dockerfile")
    return path.read_text(encoding="utf-8")


def test_dockerfile_pins_the_base_image_and_model_revision():
    dockerfile = _dockerfile()
    assert re.search(r"^FROM python:3\.12-slim@sha256:[0-9a-f]{64}$", dockerfile, re.M)
    assert f"revision='{MODEL_REVISION}'" in dockerfile
    assert re.fullmatch(r"[0-9a-f]{40}", MODEL_REVISION)
    assert "--no-deps -r requirements-lock.txt" in dockerfile and "pip check" in dockerfile


def _lock() -> dict[str, str]:
    path = API / "requirements-lock.txt"
    if not path.exists():
        pytest.skip("checks the repo")
    pins = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            name, sep, version = line.partition("==")
            assert sep, f"not an exact pin: {line}"
            pins[name.lower().replace("_", "-")] = version
    return pins


def test_every_embedding_package_matches_the_lock():
    lock = _lock()
    extra = tomllib.loads((API / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "optional-dependencies"
    ]["embeddings"]
    for requirement in extra:
        name, _, version = requirement.partition("==")
        locked = lock[name.lower().replace("_", "-")]
        assert locked.split("+")[0] == version, f"{name}: extra {version}, lock {locked}"
    assert lock["torch"].endswith("+cpu")  # never the GPU build


# Fake embedder


def test_fake_is_deterministic_and_unit_length():
    fake = FakeEmbedder()
    first = fake.embed(["Q4 vendor payments are on hold"])
    assert first == fake.embed(["Q4 vendor payments are on hold"])
    assert len(first[0]) == EMBEDDING_DIMENSIONS
    assert _is_unit(first[0])


def test_fake_puts_texts_with_shared_words_closer():
    query, related, unrelated = FakeEmbedder().embed(
        ["vendor payments", "vendor payments are on hold", "deploy pipeline failed"]
    )
    assert _cosine(query, related) > _cosine(query, unrelated)


def test_fake_folds_plurals_and_handles_any_language():
    fake = FakeEmbedder()
    payment, payments = fake.embed(["payment", "payments"])
    assert _cosine(payment, payments) > 0.99
    japanese, chinese, accented, plain = fake.embed(["支払い 保留", "付款 延迟", "résumé", "r sum"])
    assert _cosine(japanese, chinese) < 0.9  # different words, different vectors
    assert _cosine(accented, plain) < 0.9  # "résumé" is one word, not "r" + "sum"


def test_fake_refuses_blank_text():
    fake = FakeEmbedder()
    assert fake.embed([]) == []
    with pytest.raises(ValueError):
        fake.embed(["fine", "   "])


def test_fake_has_its_own_model_id():
    assert FakeEmbedder().model_id == "fake-v2" != LocalEmbedder.model_id


def test_fake_token_count_errs_high():
    fake = FakeEmbedder()
    assert fake.count_tokens("three short words") >= 4  # 1.3 pieces per word, plus 10%
    assert fake.count_tokens("app/shared/embeddings.py:61") > fake.count_tokens("app shared")
    assert fake.count_tokens("日本語のテキスト" * 50) >= 400  # one per CJK character


def test_setting_picks_the_fake(use_embedder):
    use_embedder("fake")
    assert isinstance(embeddings.get_embedder(), FakeEmbedder)
    assert embeddings.get_embedder() is embeddings.get_embedder()  # created once


def test_simultaneous_first_calls_create_one_embedder(use_embedder, monkeypatch):
    use_embedder("fake")
    created = []

    class SlowFake(FakeEmbedder):
        def __init__(self) -> None:
            time.sleep(0.05)  # like loading a model
            created.append(self)

    monkeypatch.setattr(embeddings, "FakeEmbedder", SlowFake)
    results = []
    threads = [
        threading.Thread(target=lambda: results.append(embeddings.get_embedder())) for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(created) == 1
    assert all(r is created[0] for r in results)


def test_embedder_setting_rejects_unknown_values_and_the_fake_in_production():
    with pytest.raises(ValueError):
        Settings(embedder="openai")
    with pytest.raises(ValueError):
        Settings(environment="production", embedder="fake", auth_mode="oidc")


class _Vectors:
    """Stands in for the numpy array encode() returns, so this test runs without numpy."""

    def __init__(self, count: int) -> None:
        self.count = count

    def tolist(self) -> list[list[float]]:
        return [[0.0] * EMBEDDING_DIMENSIONS for _ in range(self.count)]


def test_at_most_two_encodes_run_at_once():
    """Extra callers wait for a slot instead of each holding the model's working memory."""
    state = {"now": 0, "most": 0}
    lock = threading.Lock()

    class SlowModel:
        def encode(self, texts, **kwargs):
            with lock:
                state["now"] += 1
                state["most"] = max(state["most"], state["now"])
            time.sleep(0.05)
            with lock:
                state["now"] -= 1
            return _Vectors(len(texts))

    embedder = object.__new__(LocalEmbedder)
    embedder._model = SlowModel()
    embedder._batch_size = 32
    embedder.count_tokens = lambda text: 1
    threads = [threading.Thread(target=embedder.embed, args=(["x"],)) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert state["most"] == 2


# Real model (skipped without the embeddings extra)


@pytest.fixture(scope="module")
def local() -> LocalEmbedder:
    pytest.importorskip("sentence_transformers", reason='needs pip install -e ".[embeddings]"')
    return LocalEmbedder()


def test_local_model_shape_and_unit_length(local: LocalEmbedder):
    vectors = local.embed(["first chunk", "second chunk"])
    assert len(vectors) == 2
    assert all(len(v) == EMBEDDING_DIMENSIONS and _is_unit(v) for v in vectors)
    assert local.embed([]) == []
    with pytest.raises(ValueError):
        local.embed([""])


def test_local_model_understands_meaning_not_just_words(local: LocalEmbedder):
    # No words in common with the related text, but the same meaning.
    query, related, unrelated = local.embed(
        [
            "Why are supplier invoices not being paid?",
            "Q4 vendor payments are on hold pending a compliance review.",
            "The deploy pipeline runs nightly at 2am.",
        ]
    )
    assert _cosine(query, related) > _cosine(query, unrelated) + 0.1


def test_local_model_is_deterministic(local: LocalEmbedder):
    a, b = local.embed(["same text"]), local.embed(["same text"])
    assert all(math.isclose(x, y, abs_tol=1e-6) for x, y in zip(a[0], b[0], strict=True))


def test_local_model_warns_when_input_is_cut_off(local: LocalEmbedder, caplog):
    long_text = "CONFIDENTIAL vendor payment details. " * 80
    assert local.count_tokens(long_text) > MAX_INPUT_TOKENS
    caplog.set_level(logging.WARNING)
    local.embed([long_text])
    [record] = [r for r in caplog.records if r.name == "app.shared.embeddings"]
    assert record.texts_cut == 1
    assert "CONFIDENTIAL" not in str(vars(record))


def test_setting_picks_the_local_model(use_embedder, local: LocalEmbedder, monkeypatch):
    use_embedder("local")
    monkeypatch.setattr(embeddings, "LocalEmbedder", lambda: local)  # don't load a second copy
    assert embeddings.get_embedder() is local


def test_local_model_gives_the_same_vectors_as_when_pinned(local: LocalEmbedder):
    """Golden values, recorded from the pinned image on 2026-11-22. If a package or the model
    revision changes the vectors, stored chunks stop being comparable: re-embed everything."""
    vector = local.embed(["hello world"])[0]
    expected = [-0.034477, 0.031023, 0.006735, 0.026109, -0.039362]
    assert all(math.isclose(v, e, abs_tol=1e-4) for v, e in zip(vector[:5], expected, strict=True))
