"""Policies: a department owner's grants. Card M4-02 owns this file."""

import streamlit as st

from components.common import dev_label, show_api_error
from core import api_client


def render() -> None:
    st.title("Policies")
    dev_label("M4-02")

    # ---- REGION: grants table (active, expired, revoked) ----
    try:
        grants = api_client.get("/grants")
    except api_client.ApiError as err:
        show_api_error(err)
        grants = []
    if grants:
        st.dataframe(grants, hide_index=True)

    # ---- REGION: create grant form ----
    with st.expander("Create a grant", icon=":material/add:"):
        # TODO(M4-02): grantee, source type, max sensitivity, expiry; state plainly what becomes
        # readable, e.g. "All Finance tickets labelled internal or below, until 16 December".
        st.caption("Not built yet.")

    # ---- REGION: revoke ----
    # TODO(M4-02): revoke button with confirmation, POST /grants/{id}/revoke.
