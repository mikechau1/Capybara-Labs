"""Login and the identity sent to the API (card M1-07). No Keycloak needed.

AppTest's `user` stands in for the login cookie: `is_logged_in` and `tokens` are what
st.user would hold after a real Keycloak login.
"""

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from core import auth

APP = str(Path(__file__).parent.parent / "app.py")

ME = {
    "user_id": "012be0f9-48d7-5b8c-b52a-478d491904b4",
    "username": "eng.manager",
    "display_name": "Maya Chen",
    "department": "engineering",
    "role": "manager",
    "is_admin": False,
}
SIGNED_IN = {"is_logged_in": True, "name": "Maya Chen", "tokens": {"access": "the-token"}}


class FakeApi:
    """Answers httpx requests in place of the API and records the headers it was sent."""

    def __init__(self, me_status: int = 200) -> None:
        self.me_status = me_status
        self.headers: list[dict] = []

    def __call__(self, method: str, url: str, headers: dict, **kwargs) -> httpx.Response:
        self.headers.append(headers)
        request = httpx.Request(method, url)
        if url.endswith("/me"):
            body = ME if self.me_status == 200 else {"detail": f"Refused ({self.me_status})."}
            return httpx.Response(self.me_status, json=body, request=request)
        return httpx.Response(501, json={"detail": "Not implemented yet."}, request=request)


@pytest.fixture
def oidc(monkeypatch):
    monkeypatch.setattr("core.config.AUTH_MODE", "oidc")


def run_app(user: dict, api: FakeApi, monkeypatch) -> AppTest:
    monkeypatch.setattr(httpx, "request", api)
    at = AppTest.from_file(APP)
    at.user = user
    return at.run()


def test_signed_out_user_sees_only_the_login_button(oidc, monkeypatch):
    api = FakeApi()
    at = run_app({"is_logged_in": False}, api, monkeypatch)
    assert not at.exception
    assert [b.label for b in at.button] == ["Log in with your company account"]
    assert api.headers == []  # nothing reaches the API before login


def test_signed_in_user_calls_the_api_with_their_token(oidc, monkeypatch):
    api = FakeApi()
    at = run_app(SIGNED_IN, api, monkeypatch)
    assert not at.exception
    assert api.headers[0] == {"Authorization": "Bearer the-token"}
    assert "Maya Chen" in at.sidebar.markdown[0].value
    assert "Log out" in [b.label for b in at.sidebar.button]


def test_expired_token_asks_to_log_in_again(oidc, monkeypatch):
    at = run_app(SIGNED_IN, FakeApi(me_status=401), monkeypatch)
    assert not at.exception
    assert [b.label for b in at.button] == ["Log in again"]
    assert not at.error


def test_account_without_department_shows_the_api_reason(oidc, monkeypatch):
    at = run_app(SIGNED_IN, FakeApi(me_status=403), monkeypatch)
    assert not at.exception
    assert at.error[0].value == "Refused (403)."
    assert "Log in again" not in [b.label for b in at.button]


def test_keycloak_down_shows_the_error_not_a_login_button(oidc, monkeypatch):
    at = run_app(SIGNED_IN, FakeApi(me_status=503), monkeypatch)
    assert not at.exception
    assert at.error
    assert "Log in again" not in [b.label for b in at.button]


def test_dev_mode_401_is_not_treated_as_an_expired_session(monkeypatch):
    monkeypatch.setattr("core.config.AUTH_MODE", "dev")
    at = run_app({}, FakeApi(me_status=401), monkeypatch)
    assert not at.exception
    assert "Log in again" not in [b.label for b in at.button]


def test_oidc_without_a_token_sends_no_header(oidc, monkeypatch):
    monkeypatch.setattr(auth, "st", SimpleNamespace(user=SimpleNamespace(tokens={})))
    assert auth.auth_headers() == {}
