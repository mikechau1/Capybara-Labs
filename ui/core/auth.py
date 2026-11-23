"""Login and the identity sent to the API. Card M1-07 owns this file."""

import streamlit as st

from components.login_screen import render_login_screen
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
        render_login_screen(
            heading="Ask the whole company.",
            text="Answers come from Engineering and Finance docs, tickets and Discord threads, "
            "using only the parts you're allowed to read.",
            button_label="Log in with your company account",
            on_click=st.login,
        )
        st.stop()


def ask_to_log_in_again() -> None:
    """Stop the page because the API refused the saved access token.

    Streamlit saves the access token at login and never refreshes it, so once it expires
    (30 minutes, set in the Keycloak realm) the fix is a fresh login. While the Keycloak
    session is still open, that is a redirect with no password prompt.
    """
    render_login_screen(
        heading="Your session has expired.",
        text="Sessions last 30 minutes. Log in again to continue; if you're still signed in "
        "to your company account, it takes one click.",
        button_label="Log in again",
        on_click=st.login,
    )
    st.stop()


def auth_headers() -> dict[str, str]:
    if config.AUTH_MODE == "dev":
        return {"X-Dev-User": st.session_state.get("dev_user", DEV_USERNAMES[0])}
    # Saved at login because of expose_tokens = "access" in .streamlit/secrets.toml. Without
    # it there is no token; the API then answers 401 and the user is asked to log in again.
    token = st.user.tokens.get("access")
    return {"Authorization": f"Bearer {token}"} if token else {}


def current_user() -> dict:
    """The /me response, loaded once per run by app.py."""
    return st.session_state["me"]
