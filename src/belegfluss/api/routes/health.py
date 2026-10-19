from fastapi import APIRouter
from pydantic import BaseModel

from belegfluss import __version__

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: str
    version: str


@router.get("/health")
def health() -> Health:
    return Health(status="ok", version=__version__)
