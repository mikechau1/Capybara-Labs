import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(environment="test", auth_mode="dev")
    return TestClient(app)


def as_user(username: str) -> dict[str, str]:
    return {"X-Dev-User": username}
