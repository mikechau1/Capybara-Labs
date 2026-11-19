"""Sources: sync status and "Sync now". Card M4-10 owns this file."""

import streamlit as st

from components.common import dev_label, show_api_error
from core import api_client


def render() -> None:
    st.title("Sources")
    dev_label("M4-10")
    try:
        sources = api_client.get("/sources")
    except api_client.ApiError as err:
        show_api_error(err)
        return

    for source in sources:
        with st.container(border=True):
            name_col, status_col, action_col = st.columns([3, 2, 1])
            name_col.markdown(f"**{source['name']}**")
            name_col.caption(f"{source['department'].title()} · {source['source_type']}")
            status_col.write(f"{source['item_count']} items · {source['last_sync_status']}")
            if source.get("last_error"):
                status_col.error(source["last_error"])
            if action_col.button("Sync now", key=f"sync-{source['id']}"):
                try:
                    api_client.post(f"/sources/{source['id']}/sync")
                except api_client.ApiError as err:
                    show_api_error(err)
