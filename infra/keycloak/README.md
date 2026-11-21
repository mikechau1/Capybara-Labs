# Keycloak realm

Card M1-05. `capybara-realm.json` is the whole realm: users, departments, roles and the two clients. Keycloak imports it when it starts with `docker compose --profile sso up`.

**The import only runs when the realm does not exist yet.** Keycloak in dev mode keeps no data between containers, so after editing the file, recreate the container:

```bash
docker compose --profile sso up -d --force-recreate idp
```

Admin console: http://localhost:8080 (`KEYCLOAK_ADMIN_USER` / `KEYCLOAK_ADMIN_PASSWORD` from `.env`). Changes made there are lost on the next recreate; put them in the JSON instead.

## What the realm contains

- Realm `capybara`.
- Groups `engineering` and `finance`. A user's group is their department; every user is in exactly one.
- Realm roles `member`, `manager`, `owner`, and `app-admin`. Every user has exactly one of the first three. `app-admin` is the separate admin flag and gives no data access.
- The demo users from `api/app/modules/auth/dev_users.py`, same usernames. Logins are in [docs/demo-users.md](../../docs/demo-users.md). User IDs are fixed (UUIDv5 of `capybara-labs/<username>`), so they are the same after every fresh start.
- Client `capybara-ui`: the login client for Streamlit (redirect `http://localhost:8501/oauth2callback`).
- Client `capybara-api`: no login flows. It exists only as the audience of access tokens.

## Token contract (read by card M1-06)

Access tokens issued to `capybara-ui` carry:

| Claim | Example | Becomes `Principal.` |
|---|---|---|
| `sub` | `012be0f9-48d7-5b8c-b52a-478d491904b4` | `user_id` |
| `preferred_username` | `eng.manager` | `username` |
| `name` | `Maya Chen` | `display_name` |
| `groups` | `["engineering"]` | `department` (the single entry) |
| `realm_access.roles` | `["manager"]` | `role` (the one of member/manager/owner), and `is_admin` (`app-admin` present) |
| `iss` | `http://localhost:8080/realms/capybara` | check equals `OIDC_ISSUER` |
| `aud` | `capybara-api` | check contains `OIDC_AUDIENCE`. A string when there is one audience, a list otherwise |

`groups` comes from a group membership mapper and `aud` from an audience mapper, both on `capybara-ui`.

**Issuer vs. address.** Keycloak is told its public address (`KC_HOSTNAME` in `docker-compose.yml`), so `iss` is always `http://localhost:8080/...`, even for requests from other containers. Inside Docker, `localhost` is the container itself, so the API must fetch signing keys from `http://idp:8080/realms/capybara/protocol/openid-connect/certs`, not from an address built from `OIDC_ISSUER`.

## Checking it

With Keycloak running:

```bash
python3 infra/keycloak/check_tokens.py
```

It logs in as every demo user and checks the claims above, exiting non-zero on any mismatch. Keep its `EXPECTED` table in step with this realm and `dev_users.py`.

## Local only

These settings are for the local demo and must change before deployment (card M5-02):

- Every user's password is `capybara`, and the `capybara-ui` client secret (`capybara-ui-dev-secret`) is committed.
- `capybara-ui` allows the password grant (`directAccessGrantsEnabled`), used only by `check_tokens.py`.
- Redirect and logout addresses are `http://localhost:8501`.
- `KC_HOSTNAME` is `http://localhost:8080`.
