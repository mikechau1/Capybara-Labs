# Capybara Labs

CMPE 272 project: a chatbot that answers questions from company data across departments, while each department controls who can read its data.

- Design: [docs/architecture.md](docs/architecture.md)
- How we work: [CONTRIBUTING.md](CONTRIBUTING.md)
- Tasks: [project board](https://github.com/users/mikechau1/projects/2)

## Run it

**With Docker** (needs Docker Desktop):

```bash
cp .env.example .env
docker compose up --build
```

- UI: http://localhost:8501 (pick a demo user from the sidebar dropdown)
- API docs: http://localhost:8000/docs

Add Keycloak with `docker compose --profile sso up --build` (admin console on http://localhost:8080). You only need it for the SSO cards.

**Without Docker**, one terminal per service:

```bash
cd api
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
AUTH_MODE=dev uvicorn app.main:app --reload         # Windows PowerShell: $env:AUTH_MODE="dev"; uvicorn ...
```

```bash
cd ui
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
AUTH_MODE=dev streamlit run app.py
```

**Checks** (run from the repo root, and `pytest` inside `api/` and `ui/`):

```bash
ruff check . && ruff format --check .
```

## Where your card goes

### API (`api/app/`)

| Path | What | Cards |
|---|---|---|
| `main.py`, `config.py` | App factory, settings | M1-03 |
| `shared/types.py` | Roles, sensitivity, pools, the user type | shared |
| `shared/embeddings.py` | Text to vectors | M2-03 |
| `modules/auth/` | Token validation, demo users, `/me` | M1-05, M1-06 |
| `modules/policies/scope.py` | Who may read which pools | M2-02 |
| `modules/policies/router.py` | Grants API; access requests API | M4-01; M4-04 |
| `modules/sources/connectors/` | `docs.py`, `tickets.py`, `discord.py` | M2-05, M4-07, M4-09 |
| `modules/sources/pipeline.py`, `cli.py` | Ingestion pipeline and command | M2-04 |
| `modules/sources/router.py` | Sources list, Sync now | M4-10 |
| `modules/retrieval/gateway.py` | The only reader of chunks | M2-07 |
| `modules/llm/` | Model interface, stub, provider adapter | M3-01, M3-02 |
| `modules/chat/pipeline.py` | The fixed question pipeline | M3-03, M3-04, M3-05 |
| `modules/chat/router.py` | `/chat`, conversations | M3-05, M3-06 |
| `modules/audit/` | Audit writer; audit API | M3-07; M4-03 |
| `modules/notify/` | Discord webhook to department owners | M4-06 |
| `*/models.py` | Database tables (after M1-04) | M2-01 and the module's cards |

### UI (`ui/`)

Each page is one file in `views/`, and each piece of a page that a different card builds is its own file in `components/`. Two people can work on the chat page at once without touching the same file.

| Path | What | Cards |
|---|---|---|
| `app.py`, `core/` | Entry point, login, API client, page list | M1-07 |
| `views/home.py` | Landing page | M1-07 |
| `views/chat.py` | Chat page layout | M3-08 |
| `components/conversation_list.py` | Chat sidebar: conversations | M3-06, M3-08 |
| `components/answer.py` | One answer with citations | M3-08 |
| `components/sources_panel.py` | Chat right column: sources | M3-08 |
| `components/denial_notice.py` | "You don't have access to ..." | M3-08, M4-05 |
| `components/request_access.py` | Request access dialog | M4-05 |
| `views/my_requests.py` | My access requests | M4-05 |
| `views/access_inbox.py` | Owner's request inbox | M4-05 |
| `views/policies.py` | Owner's grants | M4-02 |
| `views/audit.py` | Audit log | M4-03 |
| `views/sources.py` | Sync status, Sync now | M4-10 |

The chat page layout:

```
+------------------+------------------------------------+-------------------------+
| sidebar          | messages                           | sources panel           |
|  page navigation |  question                          |  [1] title              |
|  signed-in user  |  answer with [1] citations         |      dept · type        |
|  conversations   |  denial notice + Request access    |      snippet, link      |
|                  |  [ ask a question ]                |                         |
+------------------+------------------------------------+-------------------------+
```

Pages each role sees (hiding is a convenience; the API enforces permissions):

| Page | Member | Manager | Owner | App admin |
|---|---|---|---|---|
| Home, Ask, My access requests | yes | yes | yes | yes |
| Access requests inbox | | | yes | |
| Policies | | | yes | yes |
| Audit log, Sources | | | yes | yes |

### Everything else

| Path | What | Cards |
|---|---|---|
| `docker-compose.yml` | Local stack | M1-02 |
| `infra/keycloak/` | Realm export | M1-05 |
| `seed/` | Mock company data and the canary inventory | M2-06, M4-07, M4-09 |
| `.github/workflows/ci.yml` | Lint and tests on every pull request | M1-08 |

## Demo users (dev mode)

| Username | Department | Role |
|---|---|---|
| `eng.member` | Engineering | member |
| `eng.manager` | Engineering | manager |
| `eng.owner` | Engineering | owner |
| `fin.member` | Finance | member |
| `fin.manager` | Finance | manager |
| `fin.owner` | Finance | owner |
| `app.admin` | Engineering | member, app admin |
