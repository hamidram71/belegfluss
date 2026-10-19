"""FastAPI application factory. Run locally with ``uvicorn belegfluss.api.main:app --reload``."""

from fastapi import FastAPI

from belegfluss import __version__
from belegfluss.api.routes import documents, health


def create_app() -> FastAPI:
    app = FastAPI(
        title="Belegfluss",
        version=__version__,
        description="Three-way matching of invoices, delivery notes, purchase orders and "
        "framework contracts.",
    )
    app.include_router(health.router)
    app.include_router(documents.router)
    return app


app = create_app()
