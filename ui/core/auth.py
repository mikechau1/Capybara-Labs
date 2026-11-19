"""Login and the identity sent to the API. Card M1-07 owns this file."""

import streamlit as st

from core import config

# Keep in step with api/app/modules/auth/dev_users.py.
DEV_USERNAMES = [
    "eng.member",
    "eng.manager",
    "eng.owner",
    "fin.member",
    "fin.manager",
    "fin.owner",
    "app.admin",
]


def ensure_logged_in() -> None:
    """Stop the page until someone is logged in."""
    if config.AUTH_MODE == "dev":
        st.sidebar.selectbox("Dev login (AUTH_MODE=dev)", DEV_USERNAMES, key="dev_user")
        return
    if not st.user.is_logged_in:
        st.title("Capybara Labs")
        st.button("Log in with company SSO", on_click=st.login, type="primary")
        st.stop()


def auth_headers() -> dict[str, str]:
    if config.AUTH_MODE == "dev":
        return {"X-Dev-User": st.session_state.get("dev_user", DEV_USERNAMES[0])}
    # TODO(M1-07): confirm this works with Keycloak. Needs expose_tokens = "access" in
    # .streamlit/secrets.toml. If it does not, fall back to oauth2-proxy (see the card).
    return {"Authorization": f"Bearer {st.user.tokens['access']}"}


def current_user() -> dict:
    """The /me response, loaded once per run by app.py."""
    return st.session_state["me"]
