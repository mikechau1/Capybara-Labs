# PostgreSQL setup

`init/` runs once, when the `db` volume is first created (card M3-07). It creates:

- `capybara_app`: a group role with no login. Migrations grant it what the API may do: read and write the data tables, but only read and insert on `audit_events`, and nothing on `alembic_version`.
- The API's login (`APP_DB_USER`, default `capybara_api`), a member of `capybara_app`. Not a superuser and owns nothing, so it cannot disable triggers or alter tables.

Migrations run as `POSTGRES_USER` (the owner) through `MIGRATION_DATABASE_URL`; the API connects as the app login through `DATABASE_URL`.

If you change `APP_DB_USER` or `APP_DB_PASSWORD`, or your volume predates this, recreate it: `docker compose down -v`.

Guards:

- The API refuses to start unless its login is exactly the limited app login: a member of `capybara_app` and nothing else, with no special attributes (superuser, CREATEROLE, CREATEDB, REPLICATION, BYPASSRLS), unable to create temporary tables, schemas or objects in any schema, with no second `audit_events` anywhere, and no right to change `audit_events` (`check_app_login` in `app/db.py`). It is checked as an allowlist, so any extra right counts. An old `.env`, or a login someone gave more rights, then fails loudly instead of quietly running with them.
- Only the `migrate` service receives the owner's user name, password and URLs; Compose blanks them (including `TEST_DATABASE_URL`) for `api` and `ui`.
- Nobody but the owner may create temporary tables (one named `audit_events` would otherwise shadow the real log on that connection).

Open decisions for deployment (card M5-02): the owner used for migrations is the Postgres superuser here; a non-superuser owner would make the audit triggers bind it too. The app login can also connect to other databases on the same server (PostgreSQL grants CONNECT to everyone by default); on a shared server, revoke that.
