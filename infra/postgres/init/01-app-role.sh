#!/bin/sh
# Runs once, when the database volume is first created (card M3-07).
# Creates the API's login. It is not a superuser and owns nothing, so it cannot disable
# triggers or change tables; it gets exactly the rights of the capybara_app group role, which
# the migrations grant (SELECT and INSERT only on audit_events). Migrations themselves run as
# POSTGRES_USER, the owner. After changing these, recreate the volume: docker compose down -v
#
# The name and password are passed as psql variables, so quotes in them can't break the SQL.
set -e
psql -v ON_ERROR_STOP=1 -v app_user="$APP_DB_USER" -v app_password="$APP_DB_PASSWORD"     --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'EOSQL'
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'capybara_app') THEN
        CREATE ROLE capybara_app NOLOGIN;
    END IF;
END $$;
CREATE ROLE :"app_user" LOGIN PASSWORD :'app_password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE IN ROLE capybara_app;
EOSQL
