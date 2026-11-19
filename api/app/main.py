"""App factory. Card M1-03 owns this file.

Each module registers its own router below. To add a feature, edit your module's router,
not this file; only touch this list when you create a new module.
"""

from fastapi import FastAPI

from app.modules.audit.router import router as audit_router
from app.modules.auth.router import router as auth_router
from app.modules.chat.router import router as chat_router
from app.modules.policies.router import router as policies_router
from app.modules.sources.router import router as sources_router

API_PREFIX = "/api/v1"

ROUTERS = [auth_router, chat_router, policies_router, sources_router, audit_router]


def create_app() -> FastAPI:
    app = FastAPI(title="Capybara Labs API", version="0.1.0")

    # TODO(M1-03): structured JSON logs with a request ID, and one consistent error shape.
    # TODO(M5-03): readiness check that covers the database and Keycloak.

    @app.get("/health", tags=["ops"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    for router in ROUTERS:
        app.include_router(router, prefix=API_PREFIX)
    return app


app = create_app()
