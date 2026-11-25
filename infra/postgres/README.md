# PostgreSQL setup

`init/` runs once, when the `db` volume is first created (card M3-07). It creates:

- `capybara_app`: a group role with no login. Migrations grant it what the API may do: read and write the data tables, but only read and insert on `audit_events`, and nothing on `alembic_version`.
- The API's login (`APP_DB_USER`, default `capybara_api`), a member of `capybara_app`. Not a superuser and owns nothing, so it cannot disable triggers or alter tables.

Migrations run as `POSTGRES_USER` (the owner) through `MIGRATION_DATABASE_URL`; the API connects as the app login through `DATABASE_URL`.

If you change `APP_DB_USER` or `APP_DB_PASSWORD`, or your volume predates this, recreate it: `docker compose down -v`.

Guards:

- The API refuses to start if its login can act, directly, through role membership or by `SET ROLE`, as a role that could change the audit log: a superuser, the owner of `audit_events`, its schema or a trigger function on it, or a role with UPDATE, DELETE, TRUNCATE or TRIGGER on it (`check_app_login` in `app/db.py`). An old `.env` then fails loudly instead of quietly running with full rights.
- Only the `migrate` service receives the owner's URL and password; Compose blanks them for `api` and `ui`.
- Nobody but the owner may create temporary tables (one named `audit_events` would otherwise shadow the real log on that connection).

Open decisions for deployment (card M5-02): the owner used for migrations is the Postgres superuser here; a non-superuser owner would make the audit triggers bind it too. The app login can also connect to other databases on the same server (PostgreSQL grants CONNECT to everyone by default); on a shared server, revoke that.
