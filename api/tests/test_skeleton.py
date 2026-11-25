import pytest
from pydantic import ValidationError

from app.config import Settings
from tests.conftest import as_user


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_me_returns_dev_user(client):
    body = client.get("/api/v1/me", headers=as_user("fin.owner")).json()
    assert body["department"] == "finance"
    assert body["role"] == "owner"


def test_me_rejects_missing_or_unknown_user(client):
    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/me", headers=as_user("nobody")).status_code == 401


def test_stub_endpoints_answer_501(client):
    response = client.get("/api/v1/grants", headers=as_user("eng.owner"))
    assert response.status_code == 501
    assert "M4-01" in response.json()["detail"]


def test_dev_auth_refused_in_production():
    with pytest.raises(ValidationError, match="AUTH_MODE=dev"):
        # embedder="local" explicitly: the test run sets EMBEDDER=fake, which production also
        # refuses, and would make this pass even without the auth guard.
        Settings(environment="production", auth_mode="dev", embedder="local")


def test_a_valid_production_configuration_is_accepted():
    """So the refusals above are each about their own setting, not something global."""
    settings = Settings(environment="production", auth_mode="oidc", embedder="local")
    assert settings.environment == "production"
