"""Dev-mode users are the same people as the Keycloak realm (cards M1-05, M1-06)."""

import json
from pathlib import Path

from app.modules.auth.dev_users import DEV_USERS
from app.shared.types import Principal, Role

REALM_FILE = Path(__file__).resolve().parents[2] / "infra" / "keycloak" / "capybara-realm.json"


def _realm_principals() -> dict[str, Principal]:
    """What /me returns for each realm user in SSO mode, per the token contract."""
    users = json.loads(REALM_FILE.read_text())["users"]
    principals = {}
    for user in users:
        roles = user["realmRoles"]
        (department,) = user["groups"]
        (role,) = [r for r in roles if r in {r.value for r in Role}]
        principals[user["username"]] = Principal(
            user_id=user["id"],
            username=user["username"],
            display_name=f"{user['firstName']} {user['lastName']}",
            department=department.removeprefix("/"),
            role=Role(role),
            is_admin="app-admin" in roles,
        )
    return principals


def test_dev_users_match_the_keycloak_realm():
    assert DEV_USERS == _realm_principals()
