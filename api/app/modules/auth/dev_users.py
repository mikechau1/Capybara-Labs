"""Demo users for AUTH_MODE=dev.

Keep in step with the Keycloak realm (card M1-05) and with DEV_USERNAMES in ui/core/auth.py.
"""

from app.shared.types import Principal, Role

DEV_USERS: dict[str, Principal] = {
    p.username: p
    for p in [
        Principal(
            user_id="dev-eng-member",
            username="eng.member",
            display_name="Eli (Engineering member)",
            department="engineering",
            role=Role.MEMBER,
        ),
        Principal(
            user_id="dev-eng-manager",
            username="eng.manager",
            display_name="Maya (Engineering manager)",
            department="engineering",
            role=Role.MANAGER,
        ),
        Principal(
            user_id="dev-eng-owner",
            username="eng.owner",
            display_name="Omar (Engineering owner)",
            department="engineering",
            role=Role.OWNER,
        ),
        Principal(
            user_id="dev-fin-member",
            username="fin.member",
            display_name="Fiona (Finance member)",
            department="finance",
            role=Role.MEMBER,
        ),
        Principal(
            user_id="dev-fin-manager",
            username="fin.manager",
            display_name="Marco (Finance manager)",
            department="finance",
            role=Role.MANAGER,
        ),
        Principal(
            user_id="dev-fin-owner",
            username="fin.owner",
            display_name="Olivia (Finance owner)",
            department="finance",
            role=Role.OWNER,
        ),
        Principal(
            user_id="dev-admin",
            username="app.admin",
            display_name="Ada (App admin)",
            department="engineering",
            role=Role.MEMBER,
            is_admin=True,
        ),
    ]
}
