"""Sources for the latest answer. Card M3-08 owns this file."""

import streamlit as st


def render_sources_panel(sources: list[dict]) -> None:
    st.subheader("Sources")
    if not sources:
        st.caption("Sources for the latest answer appear here.")
        return
    for source in sources:
        with st.container(border=True):
            st.markdown(f"**[{source['number']}] {source['title']}**")
            st.caption(f"{source['department'].title()} · {source['source_type']}")
            st.write(source["snippet"])
            st.link_button("Open", source["link"])
