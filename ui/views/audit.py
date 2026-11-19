"""Audit log for app admins and department owners. Card M4-03 owns this file.

Show document titles, never chunk text.
"""

import streamlit as st

from components.common import dev_label, show_api_error
from core import api_client

EVENT_TYPES = [
    "chat",
    "grant_created",
    "grant_revoked",
    "access_request_created",
    "access_request_approved",
    "access_request_denied",
    "access_request_expired",
]


def render() -> None:
    st.title("Audit log")
    dev_label("M4-03")

    # ---- REGION: filters ----
    user_col, type_col = st.columns(2)
    params = {
        "user_id": user_col.text_input("User ID") or None,
        "event_type": type_col.selectbox("Event type", EVENT_TYPES, index=None),
    }
    # TODO(M4-03): department and time range filters.

    # ---- REGION: events table ----
    try:
        events = api_client.get("/audit", params={k: v for k, v in params.items() if v})
    except api_client.ApiError as err:
        show_api_error(err)
        return
    st.dataframe(events, hide_index=True)
