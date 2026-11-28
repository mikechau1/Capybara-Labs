"""Shared test fixtures.

- `client`: the API with dev auth, no database.
- `db`: a SQLAlchemy session on a real, migrated PostgreSQL test database. Everything a test
  writes, including `db.commit()`, is rolled back afterwards, so each test starts clean.
- `db_client`: the API with its `DbSession` dependency pointed at that same session.

Database tests need the Compose `db` service running (`docker compose up -d db`). Without it
they are skipped, unless REQUIRE_TEST_DB=1 is set (CI sets it), in which case they fail.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.main import create_app

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parent


def pytest_configure(config):
    """The fake embedder is the default for the whole run, including session-scoped fixtures
    that run before the per-test fixture below. Real-model tests build LocalEmbedder directly."""
    os.environ["EMBEDDER"] = "fake"


def _test_settings() -> Settings:
    return Settings(environment="test", auth_mode="dev")


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = _test_settings
    return TestClient(app)


def as_user(username: str) -> dict[str, str]:
    return {"X-Dev-User": username}


@pytest.fixture(autouse=True)
def _fake_embedder(monkeypatch):
    """Every test uses the fake embedder, so none loads (or downloads) the real model by
    accident. Tests of the real model ask for it explicitly (tests/test_embeddings.py)."""
    from app.shared import embeddings

    monkeypatch.setenv("EMBEDDER", "fake")
    get_settings.cache_clear()
    embeddings.reset_embedder()
    yield
    get_settings.cache_clear()
    embeddings.reset_embedder()


# Database


class _TestDatabaseSettings(BaseSettings):
    """Where the test database lives. Read from the environment, then from the repo's .env."""

    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    test_database_url: str = ""
    postgres_user: str = "capybara"
    postgres_password: str = "capybara"
    postgres_host_port: int = 5432

    def url(self) -> str:
        if self.test_database_url:
            return self.test_database_url
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@localhost:{self.postgres_host_port}/capybara_test"
        )


def _skip_or_fail(reason: str) -> None:
    if os.environ.get("REQUIRE_TEST_DB") == "1":
        pytest.fail(reason)
    pytest.skip(reason)


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    """Creates the test database from scratch once per test run and migrates it to head."""
    url = make_url(_TestDatabaseSettings().url())
    name = url.database or ""
    # The database is dropped and recreated, so refuse anything that is not clearly a test one.
    if not name.endswith("_test"):
        pytest.fail(f"The test database name must end in _test, got {name!r}.")

    server = create_engine(
        url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        # Without a limit, connecting to a port nothing listens on can hang forever on Windows.
        connect_args={"connect_timeout": 3},
    )
    try:
        with server.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError as exc:
        _skip_or_fail(f"No test database at {url.render_as_string()}: {exc.orig}")
    finally:
        server.dispose()

    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.attributes["database_url"] = url.render_as_string(hide_password=False)
    config.attributes["keep_logging"] = True
    command.upgrade(config, "head")

    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def db(db_engine: Engine) -> Iterator[Session]:
    """A session inside a transaction that is rolled back when the test ends.

    `join_transaction_mode="create_savepoint"` turns the code's own `commit()` calls into
    savepoints, so code under test can commit normally and still leave nothing behind.
    """
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def db_client(db: Session) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = _test_settings
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)
