"""API-wide conventions from card M1-03: request IDs, JSON logs and one error shape."""

import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app
from app.shared.errors import ApiError
from app.shared.logs import REQUEST_ID_HEADER, JsonFormatter, _request_id


@pytest.fixture
def test_client() -> TestClient:
    """The real app plus routes that fail on purpose."""
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(environment="test", auth_mode="dev")

    @app.get("/test/crash")
    def crash() -> None:
        raise RuntimeError("database password is hunter2")

    @app.get("/test/items/{item_id}")
    def item(item_id: int) -> dict[str, int]:
        return {"item_id": item_id}

    @app.get("/test/revoked")
    def revoked() -> None:
        raise ApiError(409, "That grant is already revoked.", code="grant_revoked")

    return TestClient(app)


def assert_error_shape(response, status: int, code: str) -> dict:
    body = response.json()
    assert response.status_code == status
    assert body["code"] == code
    assert isinstance(body["detail"], str) and body["detail"]
    assert body["request_id"] == response.headers[REQUEST_ID_HEADER]
    return body


def _request_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "app.request"]


def test_every_response_has_a_new_request_id(client):
    first = client.get("/health").headers[REQUEST_ID_HEADER]
    second = client.get("/health").headers[REQUEST_ID_HEADER]
    assert len(first) == 32
    assert first != second


def test_safe_caller_request_id_is_kept(client):
    response = client.get("/health", headers={REQUEST_ID_HEADER: "ui-trace.42"})
    assert response.headers[REQUEST_ID_HEADER] == "ui-trace.42"


def test_unsafe_caller_request_id_is_replaced(client):
    for bad in ["has spaces", "x" * 129, '{"level":"ERROR"}']:
        response = client.get("/health", headers={REQUEST_ID_HEADER: bad})
        assert response.headers[REQUEST_ID_HEADER] != bad


def test_one_log_line_per_request_with_its_id(client, caplog):
    caplog.set_level(logging.INFO)
    response = client.get("/api/v1/me", headers={"X-Dev-User": "eng.member"})

    [record] = _request_records(caplog)
    line = json.loads(JsonFormatter().format(record))
    assert line["request_id"] == response.headers[REQUEST_ID_HEADER]
    assert line["method"] == "GET"
    assert line["path"] == "/api/v1/me"
    assert line["status"] == 200
    assert line["level"] == "INFO"
    assert line["message"] == "GET /api/v1/me 200"
    assert isinstance(line["duration_ms"], float)


def test_errors_are_logged_with_their_status(client, caplog):
    caplog.set_level(logging.INFO)
    client.get("/api/v1/me")  # no user, so 401

    [record] = _request_records(caplog)
    assert record.status == 401


def test_stub_endpoints_are_not_logged_as_errors(client, caplog):
    caplog.set_level(logging.INFO)
    client.get("/api/v1/grants", headers={"X-Dev-User": "eng.owner"})  # 501 until M4-01

    [record] = _request_records(caplog)
    assert record.status == 501
    assert record.levelname == "INFO"


def test_uvicorn_colour_codes_are_dropped():
    record = logging.makeLogRecord({"msg": "Started", "color_message": "\x1b[36mStarted\x1b[0m"})
    assert "color_message" not in json.loads(JsonFormatter().format(record))


def test_logs_written_during_a_request_carry_its_id():
    token = _request_id.set("abc123")
    try:
        record = logging.makeLogRecord({"name": "app.test", "msg": "hello", "levelname": "INFO"})
        line = json.loads(JsonFormatter().format(record))
    finally:
        _request_id.reset(token)
    assert line["request_id"] == "abc123"
    assert line["message"] == "hello"


def test_logs_outside_a_request_have_no_request_id():
    record = logging.makeLogRecord({"name": "app.test", "msg": "startup"})
    assert "request_id" not in json.loads(JsonFormatter().format(record))


def test_log_level_setting_accepts_lowercase():
    assert Settings(log_level="debug").log_level == "DEBUG"


# Error shape


def test_stub_endpoint_error_shape(client):
    response = client.get("/api/v1/grants", headers={"X-Dev-User": "eng.owner"})
    body = assert_error_shape(response, 501, "not_implemented")
    assert "M4-01" in body["detail"]


def test_auth_error_shape(client):
    assert_error_shape(client.get("/api/v1/me"), 401, "unauthorized")


def test_unknown_route_and_wrong_method_error_shape(client):
    assert_error_shape(client.get("/api/v1/no-such-thing"), 404, "not_found")
    assert_error_shape(client.post("/health"), 405, "method_not_allowed")


def test_validation_error_shape_names_the_field_but_not_its_value(test_client):
    response = test_client.get("/test/items/secret-value")
    body = assert_error_shape(response, 422, "validation_error")
    assert body["detail"] == "The request is not valid."
    [error] = body["errors"]
    assert error["loc"] == ["path", "item_id"]
    assert "secret-value" not in response.text


def test_custom_error_code(test_client):
    body = assert_error_shape(test_client.get("/test/revoked"), 409, "grant_revoked")
    assert body["detail"] == "That grant is already revoked."


def test_crash_returns_500_without_leaking_and_logs_the_traceback(test_client, caplog):
    caplog.set_level(logging.INFO)
    response = test_client.get("/test/crash")

    body = assert_error_shape(response, 500, "internal_error")
    assert body["detail"] == "Internal error."
    assert "hunter2" not in response.text

    [crash] = [r for r in caplog.records if r.name == "app.shared.errors"]
    assert crash.exc_info is not None
    line = json.loads(JsonFormatter().format(crash))
    assert line["request_id"] == body["request_id"]
    assert "RuntimeError" in line["exception"]

    [request_line] = _request_records(caplog)
    assert request_line.status == 500
    assert request_line.levelname == "ERROR"
