# Architecture

## What we are building

A chatbot that answers questions from company data across departments, while each department controls who can read its data. The demo company has two departments (Engineering, Finance) and three kinds of source (docs, tickets, Discord).

## Components (one container each)

- `ui`: Streamlit. Chat, sources panel, policy, audit and request pages. No logic and no database connection; it talks only to the API.
- `api`: FastAPI. All logic, under `/api/v1`.
- `db`: PostgreSQL with pgvector. Holds everything, including embeddings.
- `idp`: Keycloak. Single sign-on over OIDC. Users, departments and roles live here.
- `ingest`: the API image run as a scheduled command.

## API modules

`auth`, `policies`, `sources`, `retrieval`, `llm`, `chat`, `audit`, `notify`. Each module's `__init__.py` says what it owns and which board cards build it.

## Glossary

- **Sensitivity**: every item is `public`, `internal` or `restricted`.
- **Pool**: one combination of department + source type + sensitivity. Access is decided per pool, never per document.
- **Scope**: the set of pools a user may read, worked out fresh on every question.
- **Baseline**: access everyone gets without a grant. Public everywhere; internal in your own department; restricted in your own department if you are a manager or owner.
- **Grant**: a row created by a department owner that adds pools for a department + minimum role, or for one named user. Grants only add access; there are no deny rules.
- **Roles**: member < manager < owner, plus a separate app-admin flag. App admins run the system but get no data access from that flag.
- **Canary**: a unique made-up string planted in non-public seed data so tests can detect leaks.

## How a question is answered (a fixed pipeline, in code)

1. Resolve the user's scope.
2. Planner (LLM call 1): turn the question into up to three sub-queries with suggested pools. It sees pool names only.
3. Retrieve: suggested pools are intersected with the scope; anything outside is recorded as denied. The scope filter sits inside the search query.
4. Answer (LLM call 2): written only from retrieved chunks, with numbered citations that code verifies.
5. Audit: one append-only row per question.
6. Show the answer, the sources, and "You don't have access to X" with a Request access button.

## Rules that must never be broken

- Only the `retrieval` module reads chunks, and it always requires a scope.
- The LLM has no tools and never sees text outside the user's scope.
- Department and sensitivity come from how a source is registered, never from content. Unknown sensitivity means `restricted`.
- The leakage tests must pass before anything merges.
