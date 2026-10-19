"""Document intake. Week 1 stores and classifies uploads; extraction follows in week 2."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status

from belegfluss.config import Settings, get_settings
from belegfluss.storage.documents import (
    LocalDocumentStore,
    StoredDocument,
    UnsupportedDocumentError,
)

router = APIRouter(prefix="/v1/documents", tags=["documents"])


def get_store(settings: Annotated[Settings, Depends(get_settings)]) -> LocalDocumentStore:
    return LocalDocumentStore(settings.storage_dir)


StoreDep = Annotated[LocalDocumentStore, Depends(get_store)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile, store: StoreDep, settings: SettingsDep
) -> StoredDocument:
    limit = settings.max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, "file too large")
    if not data:
        raise HTTPException(422, "empty file")
    try:
        return store.save(file.filename or "upload", data)
    except UnsupportedDocumentError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc


@router.get("/{document_id}")
def get_document(document_id: str, store: StoreDep) -> StoredDocument:
    document = store.get(document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    return document
