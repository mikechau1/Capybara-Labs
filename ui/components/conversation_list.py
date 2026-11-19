"""Conversation list in the chat sidebar. Cards M3-06 (API) and M3-08 (this component)."""

import streamlit as st

from core import api_client


def render_conversation_list() -> str | None:
    """Show the user's conversations; return the selected ID, or None for a new one."""
    with st.sidebar:
        st.subheader("Conversations")
        if st.button("New conversation", icon=":material/add:"):
            st.session_state["conversation_id"] = None
            st.session_state["chat_turns"] = []
        try:
            conversations = api_client.get("/conversations")
        except api_client.ApiError as err:
            st.caption("Not built yet." if err.not_built_yet else err.detail)
            conversations = []
        for conv in conversations:
            # TODO(M3-08): load the conversation's messages when selected.
            if st.button(conv["title"], key=f"conv-{conv['id']}"):
                st.session_state["conversation_id"] = conv["id"]
    return st.session_state.get("conversation_id")
