# Demo users

The mock company's users, defined in [infra/keycloak/capybara-realm.json](../infra/keycloak/capybara-realm.json). Every password is `capybara`. Local demo only; see the Keycloak README before deploying.

With `AUTH_MODE=dev` you pick the same usernames from the sidebar dropdown instead of logging in.

| Username | Name | Department | Role | App admin |
|---|---|---|---|---|
| `eng.member` | Eli Park | Engineering | member | |
| `eng.manager` | Maya Chen | Engineering | manager | |
| `eng.owner` | Omar Haddad | Engineering | owner | |
| `fin.member` | Fiona Walsh | Finance | member | |
| `fin.manager` | Marco Rossi | Finance | manager | |
| `fin.owner` | Olivia Grant | Finance | owner | |
| `app.admin` | Ada Okafor | Engineering | member | yes |

## What each can read without a grant

- **Everyone:** public items in every department.
- **Members:** also internal items in their own department.
- **Managers and owners:** also restricted items in their own department.
- **`app.admin`:** the same as an Engineering member. The admin flag runs the system (audit log, sources, revoking grants) but gives no data access.

Anything across departments needs a grant from that department's owner (cards M2-02, M4-01).

## Keycloak admin console

http://localhost:8080 with `admin` / `admin` (`KEYCLOAK_ADMIN_USER` and `KEYCLOAK_ADMIN_PASSWORD` in `.env`). It runs only with `docker compose --profile sso up`.
