"""One assistant answer with numbered citations. Card M3-08 owns this file."""

import streamlit as st

STATUS_MESSAGES = {
    "no_access": "None of the places that could answer this are open to you.",
    "nothing_found": "Nothing you have access to answers this question.",
}


def render_answer(response: dict) -> None:
    if response["status"] in STATUS_MESSAGES:
        st.info(STATUS_MESSAGES[response["status"]])
        return
    # TODO(M3-08): make each [n] in the answer link to source n in the sources panel.
    st.markdown(response["answer"])
