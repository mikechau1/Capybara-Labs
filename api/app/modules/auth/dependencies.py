import logging
from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_settings
from app.modules.auth.dev_users import DEV_USERS
from app.shared.errors import ApiError
from app.shared.types import Principal, Role

log = logging.getLogger(__name__)

# Keycloak signs access tokens with RS256. Fixing the algorithm here means a token cannot
# pick its own, such as "none" or HS256 with the public key used as the secret.
ALGORITHMS = ["RS256"]
ADMIN_ROLE = "app-admin"
_DEPARTMENT_ROLES = {role.value for role in Role}


@lru_cache
def _jwks_client(url: str) -> jwt.PyJWKClient:
    # Keeps Keycloak's public keys for five minutes, and fetches them again early when a
    # token names a key it has not seen, so Keycloak can rotate keys without a restart.
    return jwt.PyJWKClient(url, lifespan=300, timeout=5)


def get_jwks_client(
    settings: Annotated[Settings, Depends(get_settings)],
) -> jwt.PyJWKClient | None:
    """Where signing keys come from. Tests override this to sign tokens locally."""
    if not settings.oidc_jwks_url:
        return None
    return _jwks_client(settings.oidc_jwks_url)


def get_principal(
    settings: Annotated[Settings, Depends(get_settings)],
    jwks: Annotated[jwt.PyJWKClient | None, Depends(get_jwks_client)],
    authorization: Annotated[str | None, Header()] = None,
    x_dev_user: Annotated[str | None, Header()] = None,
) -> Principal:
    if settings.auth_mode == "dev":
        return _dev_principal(x_dev_user)
    return _oidc_principal(authorization, settings, jwks)


def _dev_principal(username: str | None) -> Principal:
    if username is None or username not in DEV_USERS:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown or missing X-Dev-User header")
    return DEV_USERS[username]


def _oidc_principal(
    authorization: str | None, settings: Settings, jwks: jwt.PyJWKClient | None
) -> Principal:
    if jwks is None or not settings.oidc_issuer or not settings.oidc_audience:
        log.error("AUTH_MODE=oidc needs OIDC_ISSUER, OIDC_AUDIENCE and OIDC_JWKS_URL")
        raise ApiError(503, "Sign-in is not configured on the server.")
    token = _bearer_token(authorization)
    claims = _verified_claims(token, settings, jwks)
    return _principal_from_claims(claims)


def _unauthorized(detail: str) -> ApiError:
    return ApiError(401, detail, headers={"WWW-Authenticate": "Bearer"})


def _bearer_token(authorization: str | None) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized("Missing bearer token. Log in again.")
    return token.strip()


def _verified_claims(token: str, settings: Settings, jwks: jwt.PyJWKClient) -> dict[str, Any]:
    """Signature, issuer, audience and expiry, or 401. 503 if Keycloak's keys are unreachable."""
    try:
        return jwt.decode(
            token,
            jwks.get_signing_key_from_jwt(token),
            algorithms=ALGORITHMS,
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWKClientConnectionError as exc:
        log.error("Cannot fetch signing keys from %s: %s", settings.oidc_jwks_url, exc)
        raise ApiError(503, "The sign-in service is unreachable. Try again shortly.") from exc
    except jwt.ExpiredSignatureError as exc:
        raise _unauthorized("Your session has expired. Log in again.") from exc
    except jwt.PyJWTError as exc:
        # The reason goes to the log, never to the caller.
        log.info("Rejected access token: %s", exc)
        raise _unauthorized("The access token is not valid. Log in again.") from exc


def _principal_from_claims(claims: dict[str, Any]) -> Principal:
    """Map the claims listed in infra/keycloak/README.md onto a Principal.

    A valid token whose account lacks exactly one department and one role gets 403: the
    user is known, but there is no safe way to decide what they may read.
    """
    groups = claims.get("groups")
    realm_roles = (claims.get("realm_access") or {}).get("roles") or []
    department_roles = sorted(set(realm_roles) & _DEPARTMENT_ROLES)
    username = claims.get("preferred_username") or claims["sub"]

    if not isinstance(groups, list) or len(groups) != 1 or len(department_roles) != 1:
        log.warning(
            "Account %s has groups=%s and department roles=%s; needs exactly one of each",
            username,
            groups,
            department_roles,
        )
        raise ApiError(
            403, "Your account has no single department and role. Ask an app admin to fix it."
        )

    return Principal(
        user_id=claims["sub"],
        username=username,
        display_name=claims.get("name") or username,
        department=groups[0],
        role=Role(department_roles[0]),
        is_admin=ADMIN_ROLE in realm_roles,
    )


CurrentUser = Annotated[Principal, Depends(get_principal)]
