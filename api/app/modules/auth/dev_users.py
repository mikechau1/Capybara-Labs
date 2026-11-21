"""Demo users for AUTH_MODE=dev.

The same people as the Keycloak realm (infra/keycloak/capybara-realm.json), with the same IDs
and names, so anything stored against a user ID means the same user in dev and SSO mode.
tests/test_dev_users.py fails if the two drift. Keep DEV_USERNAMES in ui/core/auth.py in step.
"""

from app.shared.types import Principal, Role

DEV_USERS: dict[str, Principal] = {
    p.username: p
    for p in [
        Principal(
            user_id="83c50624-29ee-50e9-a4dd-abef7c5aad41",
            username="eng.member",
            display_name="Eli Park",
            department="engineering",
            role=Role.MEMBER,
        ),
        Principal(
            user_id="012be0f9-48d7-5b8c-b52a-478d491904b4",
            username="eng.manager",
            display_name="Maya Chen",
            department="engineering",
            role=Role.MANAGER,
        ),
        Principal(
            user_id="488d457d-aa8e-5d70-9cda-e66d4d3aa598",
            username="eng.owner",
            display_name="Omar Haddad",
            department="engineering",
            role=Role.OWNER,
        ),
        Principal(
            user_id="5af5e95d-d4b9-574f-b5b0-3f365e34765f",
            username="fin.member",
            display_name="Fiona Walsh",
            department="finance",
            role=Role.MEMBER,
        ),
        Principal(
            user_id="f14b3b11-5a3e-533f-9e98-a52c44baa0ae",
            username="fin.manager",
            display_name="Marco Rossi",
            department="finance",
            role=Role.MANAGER,
        ),
        Principal(
            user_id="80d84202-eff7-523b-87c7-d04155521822",
            username="fin.owner",
            display_name="Olivia Grant",
            department="finance",
            role=Role.OWNER,
        ),
        Principal(
            user_id="df48e0e5-2e74-570b-95ff-50d581a87b42",
            username="app.admin",
            display_name="Ada Okafor",
            department="engineering",
            role=Role.MEMBER,
            is_admin=True,
        ),
    ]
}
