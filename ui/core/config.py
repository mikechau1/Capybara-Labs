"""UI settings from environment variables. Read them as `config.NAME` so tests can patch them."""

import os

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
AUTH_MODE = os.environ.get("AUTH_MODE", "oidc")  # "dev" or "oidc"; must match the API
# Must exceed the API's worst case for one question (see LLM_TIMEOUT_SECONDS in .env.example).
API_TIMEOUT_SECONDS = float(os.environ.get("API_TIMEOUT_SECONDS", "60"))
