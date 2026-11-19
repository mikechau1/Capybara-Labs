from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from core import api_client
from core.api_client import ApiError
from core.navigation import PAGES, visible_pages

APP = str(Path(__file__).parent.parent / "app.py")

MEMBER = {
    "user_id": "dev-eng-member",
    "username": "eng.member",
    "display_name": "Eli (Engineering member)",
    "department": "engineering",
    "role": "member",
    "is_admin": False,
}
OWNER = {**MEMBER, "role": "owner"}
ADMIN = {**MEMBER, "is_admin": True}

CHAT_RESPONSE = {
    "conversation_id": "c1",
    "answer": "Payments are blocked on vendor review [1].",
    "sources": [
        {
            "number": 1,
            "title": "Vendor review checklist",
            "department": "engineering",
            "source_type": "docs",
            "link": "https://example.com/doc",
            "snippet": "Vendor review must finish before payment.",
        }
    ],
    "denied": [{"department": "finance", "source_type": "tickets"}],
    "status": "answered",
}


def fake_api(method, path, **kwargs):
    if path == "/me":
        return MEMBER
    if path == "/chat":
        return CHAT_RESPONSE
    raise ApiError(501, "Not implemented yet. See board card X.")


@pytest.fixture(autouse=True)
def dev_mode(monkeypatch):
    monkeypatch.setattr("core.config.AUTH_MODE", "dev")


def test_pages_visible_by_role():
    keys = lambda me: {p.key for p in visible_pages(me)}  # noqa: E731
    assert keys(MEMBER) == {"home", "chat", "my_requests"}
    assert keys(OWNER) == {p.key for p in PAGES}
    assert keys(ADMIN) == {"home", "chat", "my_requests", "policies", "audit", "sources"}


def test_app_explains_when_api_is_down(monkeypatch):
    monkeypatch.setattr("core.config.API_BASE_URL", "http://127.0.0.1:9")
    at = AppTest.from_file(APP).run()
    assert not at.exception
    assert "Cannot reach the API" in at.error[0].value


def test_app_opens_home_page(monkeypatch):
    monkeypatch.setattr(api_client, "_request", fake_api)
    at = AppTest.from_file(APP).run()
    assert not at.exception
    assert at.title[0].value == "Capybara Labs"


def _render_page(key: str) -> None:
    import streamlit as st

    from core.navigation import PAGES

    st.session_state["me"] = {
        "user_id": "dev-eng-owner",
        "username": "eng.owner",
        "display_name": "Omar",
        "department": "engineering",
        "role": "owner",
        "is_admin": True,
    }
    next(p for p in PAGES if p.key == key).render()


@pytest.mark.parametrize("key", [p.key for p in PAGES])
def test_every_page_renders_against_stub_api(monkeypatch, key):
    monkeypatch.setattr(api_client, "_request", fake_api)
    at = AppTest.from_function(_render_page, kwargs={"key": key}).run()
    assert not at.exception


def test_chat_shows_answer_sources_and_denial(monkeypatch):
    monkeypatch.setattr(api_client, "_request", fake_api)
    at = AppTest.from_function(_render_page, kwargs={"key": "chat"}).run()
    at.chat_input[0].set_value("What's blocking the Q4 vendor payments?").run()
    assert not at.exception
    page_text = " ".join(m.value for m in at.markdown)
    assert "Payments are blocked" in page_text
    assert "Vendor review checklist" in page_text
    assert "You don't have access to **Finance tickets**" in page_text
    assert any(b.label == "Request access" for b in at.button)
