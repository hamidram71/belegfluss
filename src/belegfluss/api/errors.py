"""Turn failures into clear HTTP answers.

Problems with the model provider are configuration or account problems the operator can fix,
so they get a 503 (or 502 / 429) with what to do, never an opaque 500. Anything unexpected is
logged with a traceback and an error id, and the client gets only that id, no internals.
"""

from __future__ import annotations

import logging
import uuid

import openai
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

log = logging.getLogger("belegfluss.api")


def _answer(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": message})


def _is_quota_error(exc: openai.RateLimitError) -> bool:
    """The quota code arrives as ``exc.code``, nested in ``exc.body`` or only in the message,
    depending on the SDK version and response shape; check all three."""
    body: dict[str, object] = exc.body if isinstance(exc.body, dict) else {}
    inner = body.get("error")
    nested: dict[str, object] = inner if isinstance(inner, dict) else {}
    codes = {getattr(exc, "code", None), body.get("code"), nested.get("code")}
    return "insufficient_quota" in codes or "insufficient_quota" in str(exc)


def provider_error_response(exc: openai.OpenAIError) -> JSONResponse:
    if isinstance(exc, openai.AuthenticationError):
        return _answer(
            503,
            "The model provider rejected the API key (invalid, revoked or expired). "
            "Create a new key and update the OPENAI_API_KEY secret.",
        )
    if isinstance(exc, openai.PermissionDeniedError):
        return _answer(
            503,
            "The API key has no access to the configured model or project. "
            "Check BELEGFLUSS_LLM_MODEL and the key's project permissions.",
        )
    if isinstance(exc, openai.NotFoundError):
        return _answer(
            503,
            "The configured model was not found. Check BELEGFLUSS_LLM_MODEL and "
            "BELEGFLUSS_EMBEDDING_MODEL.",
        )
    if isinstance(exc, openai.RateLimitError):
        if _is_quota_error(exc):
            return _answer(
                503,
                "The model provider account has no remaining credit. Add credit "
                "under Billing, then retry.",
            )
        return _answer(429, "The model provider is rate limiting requests. Retry shortly.")
    if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)):
        return _answer(502, "The model provider could not be reached. Retry shortly.")
    return _answer(502, f"The model provider returned an error ({type(exc).__name__}).")


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(openai.OpenAIError)
    async def provider_error(request: Request, exc: openai.OpenAIError) -> JSONResponse:
        log.warning("model provider error on %s: %s", request.url.path, type(exc).__name__)
        return provider_error_response(exc)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        error_id = uuid.uuid4().hex[:12]
        log.exception("unexpected error %s on %s", error_id, request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Internal error. Quote this id when reporting it.",
                "error_id": error_id,
            },
        )
