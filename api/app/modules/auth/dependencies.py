from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_settings
from app.modules.auth.dev_users import DEV_USERS
from app.shared.types import Principal


def get_principal(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
    x_dev_user: Annotated[str | None, Header()] = None,
) -> Principal:
    if settings.auth_mode == "dev":
        return _dev_principal(x_dev_user)
    return _oidc_principal(authorization, settings)


def _dev_principal(username: str | None) -> Principal:
    if username is None or username not in DEV_USERS:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown or missing X-Dev-User header")
    return DEV_USERS[username]


def _oidc_principal(authorization: str | None, settings: Settings) -> Principal:
    # TODO(M1-06): validate the bearer token (signature via Keycloak's keys, issuer, audience,
    # expiry) and build the Principal from its claims. Reject anything else with 401.
    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED, "OIDC token validation is not implemented yet (card M1-06)"
    )


CurrentUser = Annotated[Principal, Depends(get_principal)]
