"""Which pages exist and who sees them. Add a page with one line in PAGES.

Hiding a page is a convenience only: the API still enforces every permission.
"""

from collections.abc import Callable
from dataclasses import dataclass

import streamlit as st

from views import access_inbox, audit, chat, home, my_requests, policies, sources


def everyone(me: dict) -> bool:
    return True


def owner(me: dict) -> bool:
    return me["role"] == "owner"


def owner_or_admin(me: dict) -> bool:
    return me["role"] == "owner" or me["is_admin"]


@dataclass(frozen=True)
class PageSpec:
    key: str
    title: str
    icon: str
    section: str
    render: Callable[[], None]
    visible_to: Callable[[dict], bool]


PAGES = [
    PageSpec("home", "Home", ":material/home:", "Workspace", home.render, everyone),
    PageSpec("chat", "Ask", ":material/chat:", "Workspace", chat.render, everyone),
    PageSpec(
        "my_requests",
        "My access requests",
        ":material/outgoing_mail:",
        "Workspace",
        my_requests.render,
        everyone,
    ),
    PageSpec(
        "access_inbox",
        "Access requests inbox",
        ":material/inbox:",
        "Department",
        access_inbox.render,
        owner,
    ),
    PageSpec(
        "policies", "Policies", ":material/policy:", "Department", policies.render, owner_or_admin
    ),
    PageSpec("audit", "Audit log", ":material/history:", "Oversight", audit.render, owner_or_admin),
    PageSpec(
        "sources", "Sources", ":material/database:", "Oversight", sources.render, owner_or_admin
    ),
]


def visible_pages(me: dict) -> list[PageSpec]:
    return [page for page in PAGES if page.visible_to(me)]


def build_navigation(me: dict):
    sections: dict[str, list] = {}
    for spec in visible_pages(me):
        page = st.Page(
            spec.render,
            title=spec.title,
            icon=spec.icon,
            url_path=spec.key,
            default=spec.key == "home",
        )
        sections.setdefault(spec.section, []).append(page)
    return st.navigation(sections)
