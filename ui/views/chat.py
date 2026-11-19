"""Chat page: the main screen. Card M3-08 owns the layout.

Layout and region owners:
    sidebar     conversation list            components/conversation_list.py   M3-06, M3-08
    left        messages and question box    this file + components/answer.py   M3-08
    left        denial notice per answer     components/denial_notice.py        M3-08, M4-05
    right       sources for latest answer    components/sources_panel.py        M3-08
"""

import streamlit as st

from components.answer import render_answer
from components.common import dev_label, show_api_error
from components.conversation_list import render_conversation_list
from components.denial_notice import render_denial_notice
from components.sources_panel import render_sources_panel
from core import api_client


def render() -> None:
    st.title("Ask a question")
    dev_label("M3-08")
    turns: list[dict] = st.session_state.setdefault("chat_turns", [])

    # ---- REGION: conversation list (sidebar) ----
    conversation_id = render_conversation_list()

    messages_col, sources_col = st.columns([3, 2], gap="large")

    # ---- REGION: messages and question box ----
    with messages_col:
        for i, turn in enumerate(turns):
            with st.chat_message("user"):
                st.write(turn["question"])
            with st.chat_message("assistant"):
                render_answer(turn["response"])
                render_denial_notice(turn["response"]["denied"], turn["question"], f"turn{i}")

        question = st.chat_input("Ask about any department")
        if question:
            body = {"question": question, "conversation_id": conversation_id}
            try:
                response = api_client.post("/chat", json=body)
            except api_client.ApiError as err:
                show_api_error(err)
            else:
                st.session_state["conversation_id"] = response["conversation_id"]
                turns.append({"question": question, "response": response})
                st.rerun()

    # ---- REGION: sources panel ----
    with sources_col:
        latest = turns[-1]["response"]["sources"] if turns else []
        render_sources_panel(latest)
