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


def test_the_stub_record_cannot_be_rewritten_after_the_call():
    stub = StubLLM()
    pools = dict(POOLS)
    stub.plan("q", pools, metrics={})
    chunks = [_chunk(1, "CANARY-1"), _chunk(2, "CANARY-2"), _chunk(3, "CANARY-3")]
    history = [Turn(role="user", text="H-1"), Turn(role="assistant", text="H-2")]
    stub.answer("q", chunks, history)
    # What a later pipeline step might do to its own objects after the model saw them.
    pools.clear()
    chunks[0].text = "redacted"
    chunks[:] = chunks[1:]
    history.pop()
    [plan_call, answer_call] = stub.calls
    assert plan_call.arguments["pool_descriptions"] == POOLS
    assert [c.text for c in answer_call.arguments["chunks"]] == ["CANARY-1", "CANARY-2", "CANARY-3"]
    assert [t.text for t in answer_call.arguments["history"]] == ["H-1", "H-2"]


def test_scripted_stub_answers_are_returned_in_order_and_still_recorded():
    scripted = [DraftAnswer(text="see [2] and [9]", cited=[2]), DraftAnswer(text="b", cited=[])]
    stub = StubLLM(answers=scripted)
    assert stub.answer("q1", [_chunk(1)], []) == scripted[0]
    assert stub.answer("q2", [_chunk(1)], []) == scripted[1]
    assert stub.answer("q3", [_chunk(1)], []).text.startswith("Stub answer to: q3")
    assert [c.arguments["question"] for c in stub.calls] == ["q1", "q2", "q3"]


def test_stub_records_every_input_exactly():
    """M2-08 asserts on these records."""
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
    for chunk in chunks:
        labels = f"{chunk.department}/{chunk.source_type.value}/{chunk.sensitivity.value}"
        assert labels in draft.text
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
        self.deadlines: list[float | None] = []

    def _maybe_fail(self) -> None:
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error

    def plan(self, question, pool_descriptions, metrics, *, deadline=None):
        self.deadlines.append(deadline)
        self._maybe_fail()
        return Plan(sub_queries=[SubQuery(query=question)])

    def answer(self, question, chunks, history, *, deadline=None):
        self.deadlines.append(deadline)
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


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_no_call_is_started_that_cannot_finish_before_the_deadline():
    inner = _Flaky(0, LLMUnavailable("timeout"))
    clock = _Clock()
    llm = RetryingLLM(inner, pause_seconds=0, timeout_seconds=8, clock=clock)
    with pytest.raises(LLMUnavailable):
        llm.plan("q", POOLS, {}, deadline=clock.now + 7.9)
    assert inner.calls == 0
    assert llm.plan("q", POOLS, {}, deadline=clock.now + 8) is not None
    assert inner.calls == 1


def test_no_retry_when_the_deadline_is_too_close():
    inner = _Flaky(1, LLMUnavailable("timeout"))
    clock = _Clock()
    llm = RetryingLLM(inner, pause_seconds=0.5, timeout_seconds=8, clock=clock)
    with pytest.raises(LLMUnavailable):
        llm.plan("q", POOLS, {}, deadline=clock.now + 8.4)  # room for one call, not pause + two
    assert inner.calls == 1
    inner = _Flaky(1, LLMUnavailable("timeout"))
    llm = RetryingLLM(inner, pause_seconds=0, timeout_seconds=8, clock=clock)
    llm.plan("q", POOLS, {}, deadline=clock.now + 20)
    assert inner.calls == 2


def test_get_llm_uses_the_timeout_setting():
    assert get_llm(Settings(llm_timeout_seconds=3)).timeout_seconds == 3


def test_the_retry_pauses_first(monkeypatch):
    import app.modules.llm as llm_module

    pauses = []
    monkeypatch.setattr(llm_module.time, "sleep", pauses.append)
    RetryingLLM(_Flaky(1, LLMUnavailable("timeout")), pause_seconds=0.5).plan("q", POOLS, {})
    assert pauses == [0.5]


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


@pytest.mark.parametrize(
    "raw",
    [
        {"sub_queries": []},
        {"sub_queries": [{"query": "  "}]},
        {"sub_queries": [{"query": "q", "department": "Finance"}]},
        {"sub_queries": [{"query": "q", "department": "finance team"}]},
    ],
)
def test_plans_the_pipeline_cannot_use_are_bad_output(raw):
    with pytest.raises(LLMBadOutput):
        parse_plan(raw)


@pytest.mark.parametrize(
    "sub_query",
    [
        {"query": "q", "department": "marketing"},  # not a pool the model was given
        {"query": "q", "department": "finance", "source_type": "discord"},
    ],
)
def test_a_plan_naming_a_pool_it_was_not_given_is_bad_output(sub_query):
    pools = {"finance/docs": "d", "finance/tickets": "t", "engineering/docs": "e"}
    with pytest.raises(LLMBadOutput, match="not given"):
        parse_plan({"sub_queries": [sub_query]}, pools)


def test_a_plan_within_the_given_pools_is_accepted():
    pools = {"finance/docs": "d", "engineering/docs": "e"}
    raw = {
        "sub_queries": [
            {"query": "q", "department": "finance", "source_type": "docs"},
            {"query": "q", "department": "engineering"},
            {"query": "q", "source_type": "docs"},
            {"query": "q"},
        ]
    }
    assert len(parse_plan(raw, pools).sub_queries) == 4


@pytest.mark.parametrize(
    ("parse", "raw"),
    [
        (parse_plan, '{"sub_queries": [{"query": "SECRET-PLAN", "source_type": "slack"}]}'),
        (parse_answer, '{"text": "SECRET-ANSWER from a restricted chunk"}'),
        (parse_answer, "SECRET-ANSWER not json"),
    ],
)
def test_parse_errors_carry_no_model_output_and_no_chained_error(parse, raw):
    with pytest.raises(LLMBadOutput) as error:
        parse(raw)
    assert "SECRET" not in str(error.value)
    # A chained pydantic error would carry the model output (input_value=...) into logs.
    assert error.value.__cause__ is None and error.value.__suppress_context__


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
    "langgraph",
    "haystack",
    "semantic_kernel",
    "smolagents",
    "aisuite",
    "agents",  # the OpenAI Agents SDK's import name
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
    "openrouter.ai",
    "api.deepseek.com",
    "api.x.ai",
    "api.fireworks.ai",
    "api.perplexity.ai",
    ":11434",  # Ollama's default port
)
# Calls that load a module by name. Any function whose name ends in "import_module" counts, so
# an alias like `from importlib import import_module as load` is caught where it's imported.
_DYNAMIC_IMPORTS = {
    "__import__",
    "find_spec",
    "resolve_name",  # pkgutil
    "locate",  # pydoc
    "run_module",  # runpy
    "run_path",
    "spec_from_file_location",
    "spec_from_loader",
}
# Connection settings a real provider adapter (card M3-02) will read. Only app/modules/llm and
# the settings class may use them: with a base URL and key, any module could call the model with
# plain HTTP, which no import or hostname check can see.
LLM_CONNECTION_SETTINGS = {"llm_api_key", "llm_base_url", "llm_endpoint", "llm_model"}


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


def _loads_modules(name: str) -> bool:
    return name in _DYNAMIC_IMPORTS or name.endswith("import_module")


def _fromlist(call: ast.Call) -> list[str]:
    for keyword in call.keywords:
        if keyword.arg == "fromlist" and isinstance(keyword.value, ast.List | ast.Tuple):
            return [
                e.value
                for e in keyword.value.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            ]
    return []


def _builtin(func: ast.expr) -> bool:
    """`compile(...)` or `builtins.compile(...)`, not a method that shares the name
    (`re.compile`). exec and eval are flagged on any receiver (`b.exec`, `sys.modules[...]`)."""
    if isinstance(func, ast.Name):
        return True
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id in {"builtins", "__builtins__"}
    )


def provider_imports(source: str) -> list[str]:
    """Ways a Python source file reaches a model provider (empty list = clean).

    A lint for the routes code normally takes, not a sandbox: deliberately obfuscated code
    (getattr on builtins, sys.modules, strings built at run time) can still get past it, which
    is what review is for.
    """
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if _is_provider(a.name)]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            found += [n for n in names if _is_provider(n)]
            found += [
                f"loader {a.asname or a.name}"
                for a in node.names
                if a.name.endswith("import_module") and a.asname
            ]
        elif isinstance(node, ast.Call):
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            arg = _first_argument(node)
            if _loads_modules(called) and arg is not None:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    module = arg.value.split(":")[0]  # pkgutil.resolve_name("pkg:attr")
                    candidates = [module] + [f"{module}.{n}" for n in _fromlist(node)]
                    found += [c for c in candidates if _is_provider(c)]
                elif not _is_own_package(arg):
                    found.append(f"{called}() with a computed module name")
            elif (
                called in {"exec", "eval"} or (called == "compile" and _builtin(func))
            ) and arg is not None:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    try:
                        found += provider_imports(arg.value)
                    except SyntaxError:
                        pass
                elif not isinstance(arg, ast.Constant):
                    found.append(f"{called}() of computed code")
        elif isinstance(node, ast.Attribute) and node.attr in LLM_CONNECTION_SETTINGS:
            found.append(f"LLM connection setting {node.attr}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str | bytes):
            text = node.value if isinstance(node.value, str) else node.value.decode("latin-1")
            found += [f"provider host {h}" for h in PROVIDER_HOSTS if h in text]
            found += [
                f"LLM connection setting {n.upper()}"
                for n in LLM_CONNECTION_SETTINGS
                if n.upper() in text
            ]
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
        "from importlib import import_module as load\nload('openai')",
        "import pkgutil\npkgutil.resolve_name('openai:OpenAI')",
        "import pydoc\npydoc.locate('anthropic.Anthropic')",
        "import runpy\nrunpy.run_module('openai')",
        "__import__('google', fromlist=['genai'])",
        "code = 'import ' + name\nexec(code)",
        "import builtins\nbuiltins.exec(code)",
        "import builtins as b\nb.exec(code)",
        "import builtins as b\nb.exec('import openai')",
        "import sys\nsys.modules['builtins'].eval(code)",
        "import builtins\nbuiltins.compile(code, 'x', 'exec')",
        "compile(code, 'x', 'exec')",
        "URL = 'https://openrouter.ai/api/v1'",
        "URL = 'http://localhost:11434/api/chat'",
        "URL = b'https://api.openai.com/v1'",
        "import langgraph",
        "from agents import Agent",
        "httpx.post(settings.llm_base_url, json=body)",
        "key = os.environ['LLM_API_KEY']",
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
        "import re\nPATTERN = re.compile(r'(?:' + OTHER.pattern + ')')",
    ],
)
def test_the_boundary_check_allows(source):
    assert provider_imports(source) == []


def _sources_outside_llm() -> list[Path]:
    """Every Python file of the API and the UI except the llm module, the settings class (which
    declares the LLM settings) and tests, wherever later cards add them (scripts, pages)."""
    skip_dirs = {".venv", "venv", "tests", "__pycache__", "node_modules"}
    allowed = {APP / "modules" / "llm", APP / "config.py"}

    def wanted(path: Path) -> bool:
        if skip_dirs & set(path.parts):
            return False
        return not any(path == a or a in path.parents for a in allowed)

    return [p for root in (APP.parent, UI) for p in root.rglob("*.py") if wanted(p)]


def test_no_code_outside_llm_reaches_a_provider():
    sources = _sources_outside_llm()
    assert any(p.parts[-2] == "views" for p in sources), "UI sources were not found"
    offenders = [
        f"{path}: {finding}"
        for path in sources
        for finding in provider_imports(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_the_deadline_reaches_the_provider():
    inner = _Flaky(0, LLMUnavailable("timeout"))
    RetryingLLM(inner).answer("q", [_chunk(1)], [], deadline=1e12)
    assert inner.deadlines == [1e12]


def test_the_stub_takes_a_deadline_like_every_llm():
    stub = StubLLM()
    stub.plan("finance docs", POOLS, {}, deadline=1e12)
    stub.answer("q", [_chunk(1)], [], deadline=1e12)
    RetryingLLM(StubLLM()).plan("q", POOLS, {}, deadline=1e12)


@pytest.mark.parametrize("question", ["", "   ", "\n"])
def test_the_stub_planner_treats_a_blank_question_as_bad_output(question):
    with pytest.raises(LLMBadOutput) as error:
        StubLLM().plan(question, POOLS, {})
    assert error.value.__cause__ is None
