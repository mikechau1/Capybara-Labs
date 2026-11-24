# Working on a card

1. **Pick a card** from the board's Backlog or Ready column, assign yourself, and move it to In progress. Check its "Depends on" line first.
2. **Branch** from `main`, named after the card: `m2-07-retrieval-gateway`.
3. **Stay in your card's files.** Each module, page and component names the card that owns it in its first lines. The [README](README.md#where-your-card-goes) has the full map.
4. **Open a pull request** titled with the card ID, e.g. `M2-07 Retrieval gateway with access filter`. Fill in the template. Move the card to In review.
5. **Merge** after one approval and green CI. Move the card to Done.

One card per pull request. If a card turns out too big, split it on the board first.

## Shared files

These files are used by everyone. Changing them needs a second reviewer, and say so in the pull request:

| File | Why it's shared |
|---|---|
| `api/app/shared/types.py` | Roles, sensitivity, pools and the user type used by every module |
| `api/app/modules/*/schemas.py` | The contract between API and UI |
| `api/app/main.py` | Router list |
| `ui/core/api_client.py`, `ui/core/auth.py` | Every page calls the API through these |
| `ui/core/navigation.py` | Page list and who sees each page |
| `docker-compose.yml`, `.env.example` | Everyone's local setup |

If you change a schema, update the UI code that reads it in the same pull request.

## Working before your dependencies are done

- **No SSO yet?** Use `AUTH_MODE=dev`. The UI shows a dropdown of demo users and the API trusts the `X-Dev-User` header. The API refuses dev mode when `ENVIRONMENT=production`.
- **Endpoint not built yet?** Stubs answer `501 Not implemented` with the card ID, and the UI shows that as a "not built yet" note rather than an error. Build your page against the response model in `schemas.py`, and test it with a fake API as `ui/tests/test_ui_skeleton.py` does.
- **Function not built yet?** Stubs raise `NotImplementedError("Card ...")`. Write your code against the signature and fake it in your tests.

## When the dependency scan fails

CI's **Dependency scan** step fails when an installed Python package has a known vulnerability. This can happen on a pull request that never touched dependencies, because advisories are published against versions already merged. The scan runs after the tests, so the tests' results are still there to check.

1. **Look at the step's output.** It lists each package, the advisory ID and the versions that fix it.
2. **Bump the pin** to the lowest fixed version, in the `pyproject.toml` of the service that pins it. If the package isn't pinned directly (a dependency of a dependency), add it to `dependencies` with the fixed version, and a comment saying which advisory it is there for.
3. **Open the bump as its own small pull request** against `skeleton`, so everyone can rebase onto it rather than each fixing it in their own branch. Say in the team chat that it's coming.
4. **No fixed version yet?** Add `--ignore-vuln <ID>` to the `pip-audit` command in `.github/workflows/ci.yml` and `dependency-scan.yml`, with a comment saying why it's safe for now and a `TODO(<card>)` to remove it.

A weekly run (`.github/workflows/dependency-scan.yml`) scans `main` and `skeleton` the same way, and also scans the Docker images, so most new advisories show up there before they block anyone. For an image, bump its tag in `docker-compose.yml` or the `FROM` line of the service's `Dockerfile`.

## Code style

- Python 3.12. `ruff check .` and `ruff format .` from the repo root; `pre-commit install` runs them on every commit.
- Pin exact versions when adding a dependency, in the `pyproject.toml` of the service that needs it.
- Leave `TODO(<card>)` comments, never bare `TODO`, so leftovers can be traced to a card.
- Never commit `.env`, `ui/.streamlit/secrets.toml` or any key.
