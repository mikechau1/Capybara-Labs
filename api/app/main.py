"""App factory. Card M1-03 owns this file.

Each module registers its own router below. To add a feature, edit your module's router,
not this file; only touch this list when you create a new module.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.db import get_engine
from app.modules.audit.router import router as audit_router
from app.modules.auth.router import router as auth_router
from app.modules.chat.router import router as chat_router
from app.modules.policies.router import router as policies_router
from app.modules.sources.router import router as sources_router
from app.shared.errors import install_error_handlers
from app.shared.logs import RequestContextMiddleware, configure_logging

API_PREFIX = "/api/v1"

ROUTERS = [auth_router, chat_router, policies_router, sources_router, audit_router]


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Connect once at startup (outside tests), so a privileged or wrong DATABASE_URL stops the
    # process here instead of failing every request while /health stays green.
    if get_settings().environment != "test":
        get_engine()
    yield


def create_app() -> FastAPI:
    configure_logging(get_settings().log_level)
    app = FastAPI(title="Capybara Labs API", version="0.1.0", lifespan=_lifespan)
    install_error_handlers(app)
    # Added last, so it runs first: every request, error or not, gets an ID and a log line.
    app.add_middleware(RequestContextMiddleware)
    # TODO(M5-03): readiness check that covers the database and Keycloak.

    @app.get("/health", tags=["ops"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    for router in ROUTERS:
        app.include_router(router, prefix=API_PREFIX)
    return app


app = create_app()
