"""Streamlit entry point. Card M1-07 owns this file.

Run with: streamlit run app.py
Add new pages in core/navigation.py, not here.
"""

import streamlit as st

from components.common import show_api_error
from components.header import render_header
from core import api_client, auth
from core.navigation import build_navigation

st.set_page_config(page_title="Capybara Labs", page_icon=":material/forum:", layout="wide")

auth.ensure_logged_in()

try:
    me = api_client.get("/me")
except api_client.ApiError as err:
    show_api_error(err)
    st.stop()

st.session_state["me"] = me
render_header(me)
build_navigation(me).run()
