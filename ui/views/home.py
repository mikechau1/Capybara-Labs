"""Landing page. Card M1-07 owns this file."""

import streamlit as st

from components.common import dev_label
from core.auth import current_user


def render() -> None:
    me = current_user()
    st.title("Capybara Labs")
    dev_label("M1-07")
    st.write(f"Welcome, {me['display_name']}.")
    st.markdown(
        "- **Ask** questions across departments; answers cite their sources.\n"
        "- If something is off limits, you can **request access** from its department owner.\n"
        "- Track your requests under **My access requests**."
    )
