"""Provider failures become clear answers (regression: an expired key gave an opaque 500)."""

from __future__ import annotations

import httpx
import openai
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from belegfluss.api.errors import register_error_handlers


def _error(cls: type[openai.APIStatusError], status: int, body: object = None) -> Exception:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    return cls("boom", response=httpx.Response(status, request=request), body=body)


def _client(exc: Exception) -> TestClient:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/fail")
    def fail() -> None:
        raise exc

    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize(
    ("exc", "status", "text"),
    [
        (_error(openai.AuthenticationError, 401), 503, "rejected the API key"),
        (_error(openai.PermissionDeniedError, 403), 503, "no access"),
        (_error(openai.NotFoundError, 404), 503, "model was not found"),
        (
            _error(openai.RateLimitError, 429, {"error": {"code": "insufficient_quota"}}),
            503,
            "no remaining credit",
        ),
        (_error(openai.RateLimitError, 429), 429, "rate limiting"),
        (openai.APIConnectionError(request=httpx.Request("POST", "https://x")), 502, "reached"),
    ],
)
def test_provider_errors_are_explained(exc: Exception, status: int, text: str) -> None:
    response = _client(exc).get("/fail")
    assert response.status_code == status and text in response.json()["detail"]


def test_unexpected_errors_return_only_an_id() -> None:
    response = _client(RuntimeError("secret internals")).get("/fail")
    body = response.json()
    assert response.status_code == 500 and len(body["error_id"]) == 12
    assert "secret internals" not in response.text
