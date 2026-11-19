"""Access requests inbox for department owners. Card M4-05 owns this file."""

import streamlit as st

from components.common import dev_label, show_api_error
from core import api_client


def render() -> None:
    st.title("Access requests inbox")
    dev_label("M4-05")
    try:
        requests = api_client.get("/access-requests/inbox")
    except api_client.ApiError as err:
        show_api_error(err)
        return

    pending = [r for r in requests if r["status"] == "pending"]
    st.caption(f"{len(pending)} waiting for a decision")
    for req in pending:
        _render_request(req)


def _render_request(req: dict) -> None:
    with st.container(border=True):
        st.markdown(
            f"**{req['requester_id']}** ({req['requester_department']}, {req['requester_role']}) "
            f"asks for **{req['department'].title()} {req['source_type']}**"
        )
        st.write(req["justification"])
        # ---- REGION: approve form ----
        # TODO(M4-05): choose max sensitivity (default internal) and expiry (default 30 days),
        # state plainly what becomes readable, then POST /access-requests/{id}/approve.
        # ---- REGION: deny form ----
        # TODO(M4-05): optional reason, then POST /access-requests/{id}/deny.
