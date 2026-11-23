"""The signed-out front door (SSO mode). Card M1-07 owns this file.

The styles here are injected only while this screen is shown, so they never reach the
pages behind the login.
"""

from collections.abc import Callable
from pathlib import Path

import streamlit as st

_DEPARTMENTS = ["Engineering", "Finance"]
_SOURCES = ["Docs", "Tickets", "Discord"]
# The baseline every signed-in user gets (docs/demo-users.md). Grants add more.
_LEVELS = [
    ("public", "Public", "Everyone"),
    ("internal", "Internal", "Your own department"),
    ("restricted", "Restricted", "Your department's managers and owners"),
]

# Served from ui/static by Streamlit (server.enableStaticServing). Relative, so it also
# works when the login screen shows on a page such as /chat.
_LOGO = '<img class="cl-logo" src="app/static/logo.png" alt="Capybara Labs">'

_STYLE = f"<style>{(Path(__file__).parent / 'login_screen.css').read_text()}</style>"


def _pool_table() -> str:
    head_depts = "".join(f'<th colspan="3" class="cl-dept">{d}</th>' for d in _DEPARTMENTS)
    head_sources = "".join(f"<th>{s}</th>" for _ in _DEPARTMENTS for s in _SOURCES)
    rows = []
    n = 0
    for level, name, who in _LEVELS:
        cells = []
        for dept in _DEPARTMENTS:
            for shape, source in enumerate(_SOURCES):
                label = f"{dept} {source.lower()}, {name.lower()}"
                cells.append(
                    f'<td><span class="cl-pool cl-s{shape} cl-{level}" style="--n:{n}" '
                    f'role="img" aria-label="{label}"><i></i></span></td>'
                )
                n += 1
        label = f"<b>{name}</b><small>{who}</small>"
        # Two copies of the label; CSS shows the side one on wide screens, the stacked one
        # on narrow screens, so only one is ever displayed (and read out).
        stacked = f"<tr class='cl-stack'><th colspan='6' scope='col'>{label}</th></tr>"
        side = f"<th scope='row' class='cl-side'>{label}</th>"
        rows.append(f"{stacked}<tr>{side}{''.join(cells)}</tr>")
    return (
        '<table><thead><tr><td class="cl-corner"></td>'
        f'{head_depts}</tr><tr><td class="cl-corner"></td>{head_sources}</tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def render_login_screen(
    heading: str, text: str, button_label: str, on_click: Callable[[], None]
) -> None:
    """The front door: what Capybara Labs is, one way in, and who can read what."""
    st.html(_STYLE)
    pitch, pools = st.columns([5, 6], gap="large", vertical_alignment="center")
    with pitch:
        st.html(
            f'<div class="cl">{_LOGO}'
            f'<div class="cl-pitch"><h1>{heading}</h1><p>{text}</p></div></div>'
        )
        st.button(button_label, key="sso_login", type="primary", on_click=on_click)
        st.html(
            '<p class="cl cl-note">You sign in on the company login page and come straight '
            "back here.</p>"
        )
    with pools:
        st.html(
            '<section class="cl cl-map" aria-labelledby="cl-map-title">'
            '<h2 id="cl-map-title">Who can read what</h2><span class="cl-rule"></span>'
            f"{_pool_table()}"
            '<p class="cl-foot">Anything else needs a grant from that department\'s owner. '
            "When an answer says you don't have access, you can ask for it right there.</p>"
            "</section>"
        )
