# Database migrations

Each file in `versions/` is one step that changes the database structure. They run in order. `alembic upgrade head` brings any database up to the latest step.

## Apply migrations

`docker compose up` does it for you: the `migrate` service runs `alembic upgrade head` and exits, and the API starts only after it succeeds. If the API won't start, check `docker compose logs migrate`.

Migrations are copied into the image when it is built, so after pulling a teammate's new migration, rebuild and restart: `docker compose up --build`. (Rebuilding only the `migrate` service would leave the API running old code.) Without `--build`, the old image runs and reports nothing to do.

From your machine, with the API's virtual environment active and from the `api/` folder:

Windows (PowerShell):

```powershell
$env:DATABASE_URL="postgresql+psycopg://capybara:capybara@localhost:5432/capybara"
alembic upgrade head
```

macOS / Linux (bash):

```bash
DATABASE_URL=postgresql+psycopg://capybara:capybara@localhost:5432/capybara alembic upgrade head
```

Use your `POSTGRES_HOST_PORT` instead of `5432` if you changed it. Other useful commands: `alembic current` shows where a database is, `alembic history` lists the steps, `alembic downgrade -1` undoes the last step, and `alembic upgrade head --sql` prints the SQL without running it.

## Add a migration for your card

1. Define or change your tables in your module's `models.py` (see `app/db.py`).
2. Apply the existing migrations to your local database (above).
3. Generate the next step. Number it one higher than the newest file in `versions/`:

   ```bash
   alembic revision --autogenerate --rev-id 0002 -m "departments and sources"
   ```

4. **Read the generated file.** Autogenerate compares your models with the database and guesses; it misses renames and some type changes. Fix what is wrong, and make `downgrade()` undo `upgrade()`.
5. Run `alembic upgrade head`, then `alembic downgrade -1` and `alembic upgrade head` again, to check both directions.
6. Run `ruff format .` from the repo root, and commit the migration with your models in the same pull request.

**Two teammates chose the same number?** Alembic stops with "multiple heads". Whoever merges second renumbers their file, changes `revision` to match the new number, and sets `down_revision` to the number of the migration merged first.

**`alembic check` does not see enum or CHECK changes.** Adding a value to `SourceType`, `Sensitivity`, `Role` or `SYNC_STATUSES` changes a CHECK constraint, which autogenerate ignores. Write that migration by hand (drop and recreate the constraint); `tests/test_migrations.py` fails until you do. Run it locally (`REQUIRE_TEST_DB=1 pytest`): CI skips database tests until it has a Postgres service (card M1-08).

**New table with `Timestamps`?** Add the `set_updated_at` trigger to it in your migration (copy from `0002`), so `updated_at` also changes on raw SQL and upserts; `tests/test_migrations.py` checks every table has it.

Never edit a migration that has been merged; add a new one instead, because teammates' databases have already run the old one.
