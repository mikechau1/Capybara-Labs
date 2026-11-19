"""Request access dialog. Card M4-05 owns this file."""

import streamlit as st

from components.common import show_api_error
from core import api_client


@st.dialog("Request access")
def open_request_dialog(department: str, source_type: str, question: str) -> None:
    name = department.title()
    st.write(f"Ask the {name} owner for access to {name} {source_type}.")
    justification = st.text_area("Why do you need it?", value=question)
    if st.button("Send request", type="primary"):
        body = {
            "department": department,
            "source_type": source_type,
            "justification": justification,
        }
        try:
            api_client.post("/access-requests", json=body)
        except api_client.ApiError as err:
            show_api_error(err)
        else:
            st.success("Request sent. Check its status under My access requests.")
