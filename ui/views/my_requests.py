"""My access requests: status of requests the user has sent. Card M4-05 owns this file."""

import streamlit as st

from components.common import dev_label, show_api_error
from core import api_client


def render() -> None:
    st.title("My access requests")
    dev_label("M4-05")
    try:
        requests = api_client.get("/access-requests/mine")
    except api_client.ApiError as err:
        show_api_error(err)
        return

    if not requests:
        st.caption("You haven't requested access to anything yet.")
        return
    # TODO(M4-05): friendlier layout (status badge, owner's note).
    st.dataframe(requests, hide_index=True)
