# Keycloak realm

Card M1-05 puts the realm export here as `capybara-realm.json`. Keycloak imports every `.json` file in this folder when it starts with `docker compose --profile sso up`.

The realm must contain:

- realm name `capybara`
- groups `engineering` and `finance`
- roles `member`, `manager`, `owner`, plus an app-admin flag
- the demo users listed in `api/app/modules/auth/dev_users.py`, with the same usernames
- clients `capybara-ui` (login) and `capybara-api` (token audience)

Token claims must carry department, role and the admin flag.
