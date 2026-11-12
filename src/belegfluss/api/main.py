"""FastAPI application factory. Run locally with ``uvicorn belegfluss.api.main:app --reload``."""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from belegfluss import __version__
from belegfluss.api.errors import register_error_handlers
from belegfluss.api.routes import documents, health, matches

UI_DIR = Path(__file__).resolve().parent.parent / "ui"


def _configure_logging() -> None:
    """Application logs go to stdout as plain lines (JSON for match events), which Azure
    Container Apps forwards to Log Analytics."""
    logger = logging.getLogger("belegfluss")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False


def create_app() -> FastAPI:
    _configure_logging()
    app = FastAPI(
        title="Belegfluss",
        version=__version__,
        description="Three-way matching of invoices, delivery notes, purchase orders and "
        "framework contracts.",
    )
    app.include_router(health.router)
    app.include_router(documents.router)
    app.include_router(matches.router)
    register_error_handlers(app)

    # Review UI: static files compiled from ui/src/app.ts (see ui/package.json).
    app.mount("/ui", StaticFiles(directory=UI_DIR, html=True), name="ui")

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/ui/")

    return app


app = create_app()
