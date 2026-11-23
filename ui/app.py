"""Streamlit entry point. Card M1-07 owns this file.

Run with: streamlit run app.py
Add new pages in core/navigation.py, not here.
"""

from pathlib import Path

import streamlit as st

from components.common import show_api_error
from components.header import render_header
from core import api_client, auth, config
from core.navigation import build_navigation

STATIC = Path(__file__).parent / "static"
ICON = str(STATIC / "logo-icon.png")
WORDMARK = str(STATIC / "logo-wordmark.png")

st.set_page_config(page_title="Capybara Labs", page_icon=ICON, layout="wide")

auth.ensure_logged_in()

try:
    me = api_client.get("/me")
except api_client.ApiError as err:
    if err.status_code == 401 and config.AUTH_MODE == "oidc":
        auth.ask_to_log_in_again()
    if err.status_code == 403:
        # From /me, 403 means the account itself is not set up (no department or role).
        st.error(err.detail)
    else:
        show_api_error(err)
    st.stop()

st.session_state["me"] = me
st.logo(WORDMARK, icon_image=ICON, size="large")
render_header(me)
build_navigation(me).run()
