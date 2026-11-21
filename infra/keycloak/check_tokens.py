"""Log in as every demo user and check the claims in their access token. Card M1-05.

Run from the repo root while Keycloak is up (docker compose --profile sso up):

    python3 infra/keycloak/check_tokens.py

Uses the password grant on capybara-ui, which is enabled for the local realm only.
The token signature is not checked here; that is the API's job (card M1-06).
"""

import base64
import json
import sys
import urllib.parse
import urllib.request

BASE_URL = "http://localhost:8080"
REALM = "capybara"
CLIENT_ID = "capybara-ui"
CLIENT_SECRET = "capybara-ui-dev-secret"
PASSWORD = "capybara"
AUDIENCE = "capybara-api"
DEPARTMENT_ROLES = {"member", "manager", "owner"}

# Keep in step with capybara-realm.json and api/app/modules/auth/dev_users.py.
EXPECTED = {
    # username: (department, role, is_admin)
    "eng.member": ("engineering", "member", False),
    "eng.manager": ("engineering", "manager", False),
    "eng.owner": ("engineering", "owner", False),
    "fin.member": ("finance", "member", False),
    "fin.manager": ("finance", "manager", False),
    "fin.owner": ("finance", "owner", False),
    "app.admin": ("engineering", "member", True),
}


def access_token(username: str) -> str:
    form = urllib.parse.urlencode(
        {
            "grant_type": "password",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "username": username,
            "password": PASSWORD,
            "scope": "openid",
        }
    ).encode()
    url = f"{BASE_URL}/realms/{REALM}/protocol/openid-connect/token"
    with urllib.request.urlopen(url, data=form, timeout=10) as response:
        return json.load(response)["access_token"]


def claims(token: str) -> dict:
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def realm_roles(c: dict) -> set[str]:
    return set(c.get("realm_access", {}).get("roles", []))


def problems(username: str, c: dict) -> list[str]:
    department, role, is_admin = EXPECTED[username]
    roles = realm_roles(c)
    dept_roles = sorted(roles & DEPARTMENT_ROLES)
    audience = c.get("aud", [])
    audience = [audience] if isinstance(audience, str) else audience
    found = []
    if c.get("iss") != f"{BASE_URL}/realms/{REALM}":
        found.append(f"iss is {c.get('iss')}")
    if AUDIENCE not in audience:
        found.append(f"aud {audience} lacks {AUDIENCE}")
    if c.get("preferred_username") != username:
        found.append(f"preferred_username is {c.get('preferred_username')}")
    if c.get("groups") != [department]:
        found.append(f"groups is {c.get('groups')}, expected [{department!r}]")
    if dept_roles != [role]:
        found.append(f"department roles are {dept_roles}, expected [{role!r}]")
    if ("app-admin" in roles) != is_admin:
        found.append(f"app-admin is {'app-admin' in roles}, expected {is_admin}")
    if not c.get("sub") or not c.get("name"):
        found.append("sub or name is missing")
    return found


def main() -> int:
    failed = 0
    for username in EXPECTED:
        c = claims(access_token(username))
        roles = sorted(realm_roles(c) & (DEPARTMENT_ROLES | {"app-admin"}))
        print(f"{username:<12} sub={c.get('sub')}  name={c.get('name')!r}", end="")
        print(f"  groups={c.get('groups')}  roles={roles}")
        for problem in problems(username, c):
            print(f"    FAIL: {problem}")
            failed += 1
    print("All tokens match." if not failed else f"{failed} problem(s).")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
