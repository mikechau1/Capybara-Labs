"""Card M3-01: the LLM interface, the stub model, retries, and the provider-SDK boundary."""

import ast
import logging
from pathlib import Path

import pytest

from app.config import Settings
from app.modules.llm import RetryingLLM, get_llm
from app.modules.llm.base import (
    DraftAnswer,
    LLMBadOutput,
    LLMUnavailable,
    Plan,
    SubQuery,
    Turn,
    parse_answer,
    parse_plan,
    pool_key,
    split_pool_key,
)
from app.modules.llm.stub import StubLLM
from app.modules.retrieval.gateway import RetrievedChunk
from app.shared.types import Sensitivity, SourceType

APP = Path(__file__).resolve().parents[1] / "app"
UI = Path(__file__).resolve().parents[2] / "ui"


def _pools(*departments: str) -> dict[str, str]:
    return {pool_key(d, t): f"{d.title()} {t.value}" for d in departments for t in SourceType}


POOLS = _pools("engineering", "finance")


def _chunk(n: int, text: str = "Q4 vendor payments are on hold.", **fields) -> RetrievedChunk:
    values = {
        "chunk_id": f"c{n}",
        "text": text,
        "document_title": f"Doc {n}",
        "department": "finance",
        "source_type": SourceType.TICKETS,
        "sensitivity": Sensitivity.INTERNAL,
        "link": f"https://example.com/{n}",
    } | fields
    return RetrievedChunk(**values)


def _targets(plan: Plan) -> list[tuple[str | None, str | None]]:
    return [(q.department, q.source_type and q.source_type.value) for q in plan.sub_queries]


def test_pool_key():
    assert pool_key("finance", SourceType.TICKETS) == "finance/tickets"
    assert pool_key("finance", "tickets") == "finance/tickets"


@pytest.mark.parametrize("bad", ["a/b", "Finance", "", "fin ance"])
def test_pool_key_refuses_anything_but_a_department_slug(bad):
    with pytest.raises(ValueError):
        pool_key(bad, "docs")


@pytest.mark.parametrize("bad", ["finance", "finance/slack", "Finance/docs", "a/b/docs"])
def test_split_pool_key_refuses_malformed_names(bad):
    with pytest.raises(ValueError):
        split_pool_key(bad)


# Stub planner


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Any open finance tickets about vendors?", [("finance", "tickets")]),
        ("What does finance say?", [("finance", None)]),
        ("Finance docs and tickets about payroll", [("finance", None)]),  # two types named
        ("Compare engineering and finance budgets", [("engineering", None), ("finance", None)]),
        ("Show me open tickets", [(None, "tickets")]),
        ("Why is the deploy slow?", [(None, None)]),
        ("What did marketing decide?", [(None, None)]),  # no such pool
    ],
)
def test_stub_plan_targets_what_the_question_names(question, expected):
    plan = StubLLM().plan(question, POOLS, metrics={})
    assert _targets(plan) == expected
    assert all(q.query == question for q in plan.sub_queries)
    assert plan.metric is None


def test_stub_plan_caps_at_three_departments():
    pools = _pools("alpha", "beta", "gamma", "delta")
    plan = StubLLM().plan("alpha beta gamma delta", pools, metrics={})
    assert _targets(plan) == [("alpha", None), ("beta", None), ("delta", None)]


# Stub answer: must echo everything it was given, for the leakage tests (card M2-08)


def test_stub_answer_echoes_every_chunk_in_full():
    long_text = ("filler words " * 22) + "CANARY-FIN-7731 at character 280\nsecond line"
    assert long_text.index("CANARY") > 250
    chunks = [_chunk(1), _chunk(2, long_text)]
    draft = StubLLM().answer("What is on hold?", chunks, history=[])
    assert "Q4 vendor payments are on hold." in draft.text
    assert long_text in draft.text  # unchanged, including the newline
    assert "[1]" in draft.text and "[2]" in draft.text
    assert draft.cited == [1, 2]


def test_stub_answer_echoes_the_history():
    history = [
        Turn(role="user", text="earlier question"),
        Turn(role="assistant", text="HISTORY-CANARY from an old answer"),
    ]
    draft = StubLLM().answer("follow-up", [], history)
    assert "HISTORY-CANARY from an old answer" in draft.text
    assert draft.cited == []


def test_stub_records_every_input_exactly():
    """M2-08 asserts on these records, which later steps cannot rewrite."""
    stub = StubLLM()
    pools = POOLS | {"finance/docs": "CANARY-IN-DESCRIPTION"}
    stub.plan("q", pools, metrics={"open_count": "CANARY-IN-METRIC"})
    chunks = [_chunk(1, link="https://x/CANARY-IN-LINK", chunk_id="CANARY-IN-ID")]
    history = [Turn(role="assistant", text="CANARY-IN-HISTORY")]
    stub.answer("q", chunks, history)

    [plan_call, answer_call] = stub.calls
    assert plan_call.operation == "plan" and plan_call.arguments["pool_descriptions"] == pools
    assert plan_call.arguments["metrics"] == {"open_count": "CANARY-IN-METRIC"}
    assert answer_call.arguments["chunks"] == chunks
    assert answer_call.arguments["history"] == history


def test_stub_answer_echoes_every_field_of_every_chunk_and_the_history():
    chunks = [
        _chunk(
            n, f"text-{n}", link=f"https://x/link-{n}", chunk_id=f"id-{n}", document_title=f"t-{n}"
        )
        for n in range(1, 11)  # retrieval returns 10 by default
    ]
    history = [Turn(role="user", text="first"), Turn(role="assistant", text="second")]
    draft = StubLLM().answer("q", chunks, history)
    for n in range(1, 11):
        for value in (f"text-{n}", f"https://x/link-{n}", f"id-{n}", f"t-{n}", f"[{n}]"):
            assert value in draft.text
    assert "first" in draft.text and "second" in draft.text
    assert draft.cited == list(range(1, 11))


def test_shape_of_the_pipeline_on_the_stub():
    """Plan, retrieve (faked here; the real pipeline is card M3-05), answer, check citations."""
    llm = get_llm(Settings(llm_provider="stub"))
    plan = llm.plan("Any finance tickets about vendor payments?", POOLS, metrics={})
    assert _targets(plan) == [("finance", "tickets")]

    retrieved = [_chunk(1), _chunk(2)]
    draft = llm.answer("Any finance tickets about vendor payments?", retrieved, history=[])
    assert isinstance(draft, DraftAnswer)
    assert set(draft.cited) <= set(range(1, len(retrieved) + 1))


# Provider selection, settings and retries


def test_get_llm_wraps_the_configured_provider():
    llm = get_llm(Settings(llm_provider="stub"))
    assert isinstance(llm, RetryingLLM)
    assert isinstance(llm.inner, StubLLM)


@pytest.mark.parametrize("fields", [{"llm_provider": "gpt-9"}, {"llm_timeout_seconds": 0}])
def test_bad_llm_settings_are_rejected(fields):
    with pytest.raises(ValueError):
        Settings(**fields)


class _Flaky:
    """Fails the first `failures` calls with `error`, then answers."""

    def __init__(self, failures: int, error: Exception) -> None:
        self.calls, self.failures, self.error = 0, failures, error

    def _maybe_fail(self) -> None:
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error

    def plan(self, question, pool_descriptions, metrics):
        self._maybe_fail()
        return Plan(sub_queries=[SubQuery(query=question)])

    def answer(self, question, chunks, history):
        self._maybe_fail()
        return DraftAnswer(text="ok", cited=[])


def _retrying(inner) -> RetryingLLM:
    return RetryingLLM(inner, pause_seconds=0)


def test_one_retry_after_a_provider_failure():
    flaky = _Flaky(1, LLMUnavailable("timeout"))
    assert _retrying(flaky).answer("q", [], []).text == "ok"
    assert flaky.calls == 2


def test_gives_up_after_the_retry():
    flaky = _Flaky(2, LLMUnavailable("timeout"))
    with pytest.raises(LLMUnavailable):
        _retrying(flaky).plan("q", {}, {})
    assert flaky.calls == 2


@pytest.mark.parametrize("error", [LLMBadOutput("unknown source type"), ValueError("bad")])
def test_other_errors_are_not_retried(error):
    flaky = _Flaky(1, error)
    with pytest.raises(type(error)):
        _retrying(flaky).plan("q", {}, {})
    assert flaky.calls == 1


def test_attempts_must_be_positive():
    with pytest.raises(ValueError):
        RetryingLLM(StubLLM(), attempts=0)


def test_retry_log_does_not_contain_the_question_or_chunks(caplog):
    caplog.set_level(logging.WARNING)
    _retrying(_Flaky(1, LLMUnavailable("SECRET-ERROR-TEXT"))).answer(
        "secret salary question", [_chunk(1, "CONFIDENTIAL chunk")], []
    )
    assert caplog.records, "expected a retry warning"
    for record in caplog.records:
        assert "secret salary" not in str(vars(record))
        assert "CONFIDENTIAL" not in str(vars(record))
        assert "SECRET-ERROR-TEXT" not in str(vars(record))


@pytest.mark.parametrize(
    "raw", ['{"sub_queries": [{"query": "q", "source_type": "slack"}]}', "not json", {"x": 1}]
)
def test_malformed_plans_become_bad_output_without_their_text(raw):
    with pytest.raises(LLMBadOutput) as error:
        parse_plan(raw)
    assert "slack" not in str(error.value) and "not json" not in str(error.value)


def test_parse_answer():
    assert parse_answer('{"text": "ok [1]", "cited": [1]}').cited == [1]
    with pytest.raises(LLMBadOutput):
        parse_answer({"text": "missing cited"})


# Boundary: only app/modules/llm may talk to a model provider.
#
# Checked in every API and UI source file outside app/modules/llm: imports of provider SDKs by
# any route, dynamic imports whose module name isn't a plain string (can't be checked, so not
# allowed), code passed to exec/eval, and provider hostnames (a raw HTTP call needs no SDK).

PROVIDER_PACKAGES = {
    "anthropic",
    "openai",
    "google.generativeai",
    "google.genai",
    "google.cloud.aiplatform",
    "vertexai",
    "azure.ai.inference",
    "azure.ai.openai",
    "mistralai",
    "cohere",
    "ollama",
    "groq",
    "together",
    "replicate",
    "litellm",
    "llama_index",
    "llama_cpp",
    "vllm",
    "pydantic_ai",
    "instructor",
    "dspy",
    "huggingface_hub",
    "transformers",  # text generation; embeddings go through sentence_transformers (M2-03)
    "boto3",  # AWS Bedrock; move this to an allowlist if the app ever needs AWS for other things
    "botocore",
    "aiobotocore",
}
PROVIDER_PREFIXES = ("langchain",)  # langchain, langchain_core, langchain_openai, ...
PROVIDER_HOSTS = (
    "api.openai.com",
    "openai.azure.com",
    "api.anthropic.com",
    "generativelanguage.googleapis.com",
    "aiplatform.googleapis.com",
    "bedrock-runtime",
    "api.mistral.ai",
    "api.cohere",
    "api.groq.com",
    "api.together",
    "api.replicate.com",
)
_DYNAMIC_IMPORTS = {"import_module", "__import__", "find_spec"}


def _is_provider(module: str) -> bool:
    if module.startswith(PROVIDER_PREFIXES):
        return True
    return any(module == p or module.startswith(p + ".") for p in PROVIDER_PACKAGES)


def _is_own_package(arg: ast.expr) -> bool:
    """A computed name that visibly starts with "app." (e.g. f"app.modules.{name}.models")
    can only load this project's own code, so it is allowed."""
    if isinstance(arg, ast.JoinedStr) and arg.values:
        first = arg.values[0]
        return isinstance(first, ast.Constant) and str(first.value).startswith("app.")
    return False


def _first_argument(call: ast.Call) -> ast.expr | None:
    if call.args:
        return call.args[0]
    return next((k.value for k in call.keywords if k.arg in {"name", "fullname"}), None)


def provider_imports(source: str) -> list[str]:
    """Ways a Python source file reaches a model provider (empty list = clean)."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if _is_provider(a.name)]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            found += [n for n in names if _is_provider(n)]
        elif isinstance(node, ast.Call):
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            arg = _first_argument(node)
            if called in _DYNAMIC_IMPORTS and arg is not None:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if _is_provider(arg.value):
                        found.append(arg.value)
                elif not _is_own_package(arg):
                    found.append(f"{called}() with a computed module name")
            elif called in {"exec", "eval", "compile"} and isinstance(arg, ast.Constant):
                if isinstance(arg.value, str):
                    try:
                        found += provider_imports(arg.value)
                    except SyntaxError:
                        pass
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            found += [f"provider host {h}" for h in PROVIDER_HOSTS if h in node.value]
    return found


@pytest.mark.parametrize(
    "source",
    [
        "import openai",
        "import anthropic as a",
        "from openai import OpenAI",
        "from google import genai",
        "import google.generativeai as genai",
        "from google.cloud import aiplatform",
        "from azure.ai.inference import ChatCompletionsClient",
        "import langchain_community",
        "from langchain_google_genai import ChatGoogleGenerativeAI",
        "import importlib\nimportlib.import_module('openai')",
        "import importlib\nimportlib.import_module(name='openai')",
        "import importlib\nname = 'open' + 'ai'\nimportlib.import_module(name)",
        "import importlib\nimportlib.import_module(f'{x}ai')",
        "__import__('anthropic')",
        "exec('import openai')",
        "from huggingface_hub import InferenceClient",
        "import boto3",
        "import vllm",
        "from transformers import pipeline",
        "import httpx\nhttpx.post('https://api.openai.com/v1/chat/completions')",
        "URL = 'https://bedrock-runtime.us-east-1.amazonaws.com'",
    ],
)
def test_the_boundary_check_catches(source):
    assert provider_imports(source), source


@pytest.mark.parametrize(
    "source",
    [
        "from sentence_transformers import SentenceTransformer",
        "from app.modules.llm import get_llm",
        "import google.protobuf",
        "import json\njson.loads('openai')",
        "import logging\nlogging.getLogger('transformers')",
        "import importlib\nimportlib.import_module('app.modules.chat')",
        "import importlib\nimportlib.import_module(f'app.modules.{name}.models')",
    ],
)
def test_the_boundary_check_allows(source):
    assert provider_imports(source) == []


def _sources_outside_llm() -> list[Path]:
    llm_dir = APP / "modules" / "llm"
    api = [p for p in APP.rglob("*.py") if llm_dir not in p.parents]
    ui = [UI / "app.py"] + [
        p for folder in ("core", "components", "views") for p in (UI / folder).rglob("*.py")
    ]
    return api + ui


def test_no_code_outside_llm_reaches_a_provider():
    sources = _sources_outside_llm()
    assert any(p.parts[-2] == "views" for p in sources), "UI sources were not found"
    offenders = [
        f"{path}: {finding}"
        for path in sources
        for finding in provider_imports(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
