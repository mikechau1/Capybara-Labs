"""Signed-in user summary in the sidebar. Card M1-07 owns this file."""

import streamlit as st

from core import config


def render_header(me: dict) -> None:
    with st.sidebar:
        st.markdown(f"**{me['display_name']}**")
        details = f"{me['department'].title()} · {me['role']}"
        if me["is_admin"]:
            details += " · app admin"
        st.caption(details)
        if config.AUTH_MODE == "oidc":
            st.button("Log out", on_click=st.logout)
