"""'You don't have access to ...' notice. Card M3-08 (notice) and M4-05 (Request access button)."""

import streamlit as st

from components.request_access import open_request_dialog


def render_denial_notice(denied: list[dict], question: str, key_prefix: str) -> None:
    for i, pool in enumerate(denied):
        label = f"{pool['department'].title()} {pool['source_type']}"
        with st.container(border=True):
            st.markdown(f":material/lock: You don't have access to **{label}**.")
            # ---- REGION: Request access button (card M4-05) ----
            if st.button("Request access", key=f"{key_prefix}-request-{i}"):
                open_request_dialog(pool["department"], pool["source_type"], question)
