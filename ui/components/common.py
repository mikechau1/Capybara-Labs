"""Small helpers every page uses."""

import streamlit as st

from core import config
from core.api_client import ApiError


def show_api_error(err: ApiError) -> None:
    if err.not_built_yet:
        st.info(err.detail, icon=":material/construction:")
    elif err.status_code == 403:
        st.warning("You don't have permission to view this.")
    else:
        st.error(err.detail)


def dev_label(card: str) -> None:
    """Mark which board card owns a page or region. Shown only in AUTH_MODE=dev."""
    if config.AUTH_MODE == "dev":
        st.caption(f":material/view_kanban: Card {card}")
