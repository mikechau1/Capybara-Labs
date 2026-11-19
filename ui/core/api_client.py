"""The only way the UI talks to the API. Card M1-07 owns this file.

Pages call `get` and `post` with a path such as "/grants". Do not add per-feature helpers here;
keep feature code in your own page or component so teammates do not collide in this file.
"""

from typing import Any

import httpx

from core import auth, config


class ApiError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code  # 0 means the API could not be reached
        self.detail = detail

    @property
    def not_built_yet(self) -> bool:
        return self.status_code == 501


def get(path: str, params: dict[str, Any] | None = None) -> Any:
    return _request("GET", path, params=params)


def post(path: str, json: dict[str, Any] | None = None) -> Any:
    return _request("POST", path, json=json)


def _request(method: str, path: str, **kwargs: Any) -> Any:
    # TODO(M5-03): send a request ID header so one request can be traced end to end.
    url = f"{config.API_BASE_URL}/api/v1{path}"
    try:
        response = httpx.request(
            method, url, headers=auth.auth_headers(), timeout=config.API_TIMEOUT_SECONDS, **kwargs
        )
    except httpx.HTTPError as exc:
        raise ApiError(0, f"Cannot reach the API at {config.API_BASE_URL} ({exc}).") from exc

    if response.is_error:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise ApiError(response.status_code, str(detail))
    return response.json()
