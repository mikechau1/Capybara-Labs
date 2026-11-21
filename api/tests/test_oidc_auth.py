"""OIDC token validation (card M1-06).

Tokens are signed here with a local key and shaped like Keycloak's (see the token contract
in infra/keycloak/README.md), so these tests never need Keycloak.
"""

import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app
from app.modules.auth.dependencies import get_jwks_client
from app.modules.auth.dev_users import DEV_USERS

ISSUER = "http://localhost:8080/realms/capybara"
AUDIENCE = "capybara-api"
KID = "test-key"
JWKS_URL = "http://keycloak.invalid/certs"
HMAC_SECRET = "a-shared-secret-at-least-32-bytes-long"

SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class StaticJWKClient(jwt.PyJWKClient):
    """Serves fixed public keys instead of fetching them from Keycloak."""

    def __init__(self, keys: dict[str, rsa.RSAPrivateKey]) -> None:
        super().__init__(JWKS_URL)
        self._jwks = {
            "keys": [
                {
                    **json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key())),
                    "kid": kid,
                    "alg": "RS256",
                    "use": "sig",
                }
                for kid, key in keys.items()
            ]
        }

    def fetch_data(self) -> dict:
        return self._jwks


class UnreachableJWKClient(jwt.PyJWKClient):
    def __init__(self) -> None:
        super().__init__(JWKS_URL)

    def fetch_data(self) -> dict:
        raise jwt.PyJWKClientConnectionError("connection refused")


def _oidc_settings(**changes: str) -> Settings:
    values = {
        "environment": "test",
        "auth_mode": "oidc",
        "oidc_issuer": ISSUER,
        "oidc_audience": AUDIENCE,
        "oidc_jwks_url": JWKS_URL,
    }
    return Settings(**(values | changes))


def make_client(jwks: jwt.PyJWKClient | None, settings: Settings | None = None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings or _oidc_settings()
    if jwks is not None:
        app.dependency_overrides[get_jwks_client] = lambda: jwks
    return TestClient(app)


@pytest.fixture
def oidc_client() -> TestClient:
    return make_client(StaticJWKClient({KID: SIGNING_KEY}))


def keycloak_claims(username: str, **changes: object) -> dict:
    """An access token's claims for a demo user. A change set to None removes that claim."""
    user = DEV_USERS[username]
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": user.user_id,
        "iat": now,
        "exp": now + 300,
        "azp": "capybara-ui",
        "preferred_username": user.username,
        "name": user.display_name,
        "groups": [user.department],
        "realm_access": {"roles": [user.role.value] + (["app-admin"] if user.is_admin else [])},
    }
    claims.update(changes)
    return {k: v for k, v in claims.items() if v is not None}


def sign(claims: dict, key: object = SIGNING_KEY, kid: str = KID, algorithm: str = "RS256") -> str:
    return jwt.encode(claims, key, algorithm=algorithm, headers={"kid": kid})


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize("username", DEV_USERS)
def test_me_returns_the_principal_for_each_demo_user(oidc_client, username):
    response = oidc_client.get("/api/v1/me", headers=bearer(sign(keycloak_claims(username))))
    assert response.status_code == 200
    assert response.json() == DEV_USERS[username].model_dump(mode="json")


def test_audience_may_be_a_list(oidc_client):
    token = sign(keycloak_claims("eng.member", aud=["account", AUDIENCE]))
    assert oidc_client.get("/api/v1/me", headers=bearer(token)).status_code == 200


def _now() -> int:
    return int(time.time())


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({}, id="no header"),
        pytest.param({"Authorization": "Basic ZW5nOmNhcHliYXJh"}, id="not bearer"),
        pytest.param({"Authorization": "Bearer "}, id="empty token"),
        pytest.param(bearer("not.a.jwt"), id="malformed"),
        pytest.param(
            bearer(sign(keycloak_claims("eng.member", exp=_now() - 60, iat=_now() - 360))),
            id="expired",
        ),
        pytest.param(bearer(sign(keycloak_claims("eng.member", aud="account"))), id="audience"),
        pytest.param(
            bearer(sign(keycloak_claims("eng.member", iss="http://idp:8080/realms/capybara"))),
            id="issuer",
        ),
        pytest.param(bearer(sign(keycloak_claims("eng.member", exp=None))), id="no expiry"),
        pytest.param(
            bearer(sign(keycloak_claims("eng.member"), key=OTHER_KEY)), id="bad signature"
        ),
        pytest.param(
            bearer(sign(keycloak_claims("eng.member"), key=OTHER_KEY, kid="unknown")),
            id="unknown key",
        ),
        pytest.param(
            bearer(jwt.encode(keycloak_claims("eng.member"), None, algorithm="none")),
            id="alg none",
        ),
        pytest.param(
            bearer(sign(keycloak_claims("eng.member"), key=HMAC_SECRET, algorithm="HS256")),
            id="alg HS256",
        ),
    ],
)
def test_bad_tokens_get_401(oidc_client, headers):
    response = oidc_client.get("/api/v1/me", headers=headers)
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"groups": None}, id="no department"),
        pytest.param({"groups": ["engineering", "finance"]}, id="two departments"),
        pytest.param({"realm_access": {"roles": ["app-admin"]}}, id="no role"),
        pytest.param({"realm_access": {"roles": ["member", "owner"]}}, id="two roles"),
    ],
)
def test_valid_token_for_an_incomplete_account_gets_403(oidc_client, changes):
    token = sign(keycloak_claims("eng.member", **changes))
    assert oidc_client.get("/api/v1/me", headers=bearer(token)).status_code == 403


def test_unreachable_keycloak_gets_503_not_401():
    client = make_client(UnreachableJWKClient())
    token = sign(keycloak_claims("eng.member"))
    assert client.get("/api/v1/me", headers=bearer(token)).status_code == 503


@pytest.mark.parametrize("missing", ["oidc_issuer", "oidc_audience", "oidc_jwks_url"])
def test_missing_oidc_settings_get_503(missing):
    client = make_client(None, _oidc_settings(**{missing: ""}))
    token = sign(keycloak_claims("eng.member"))
    assert client.get("/api/v1/me", headers=bearer(token)).status_code == 503
