"""Document intake and extraction."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel

from belegfluss.config import Settings, get_settings
from belegfluss.domain.documents import DocumentFormat
from belegfluss.domain.models import DeliveryNote, Invoice
from belegfluss.extraction.cii import EInvoiceParseError
from belegfluss.extraction.llm import (
    LLMExtractionError,
    LLMNotConfiguredError,
    StructuredLLM,
    create_llm,
)
from belegfluss.extraction.llm_extract import ExtractionError
from belegfluss.extraction.pipeline import ExtractionMethod, extract_delivery_note, extract_invoice
from belegfluss.master_data import MasterData
from belegfluss.storage.documents import (
    LocalDocumentStore,
    StoredDocument,
    UnsupportedDocumentError,
)

router = APIRouter(prefix="/v1/documents", tags=["documents"])


def get_store(settings: Annotated[Settings, Depends(get_settings)]) -> LocalDocumentStore:
    return LocalDocumentStore(settings.storage_dir)


def get_master_data(settings: Annotated[Settings, Depends(get_settings)]) -> MasterData:
    try:
        return MasterData.load(settings.master_data_dir)
    except FileNotFoundError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"master data not found in {settings.master_data_dir}; generate the dataset first",
        ) from exc


def get_llm(settings: Annotated[Settings, Depends(get_settings)]) -> StructuredLLM | None:
    try:
        return create_llm(settings)
    except LLMNotConfiguredError:
        return None  # e-invoices still work; PDFs and scans will return 503


StoreDep = Annotated[LocalDocumentStore, Depends(get_store)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
MasterDep = Annotated[MasterData, Depends(get_master_data)]
LLMDep = Annotated[StructuredLLM | None, Depends(get_llm)]


class Usage(BaseModel):
    llm_calls: int
    input_tokens: int
    output_tokens: int
    seconds: float


class ExtractionResponse(BaseModel):
    document_id: str
    method: ExtractionMethod
    input_format: DocumentFormat
    document: Invoice | DeliveryNote
    usage: Usage


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


@router.post("/{document_id}/extract")
def extract_document(
    document_id: str,
    kind: Literal["invoice", "delivery_note"],
    store: StoreDep,
    master: MasterDep,
    llm: LLMDep,
) -> ExtractionResponse:
    data = store.read(document_id)
    if data is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    try:
        result = (
            extract_invoice(data, master, llm)
            if kind == "invoice"
            else extract_delivery_note(data, master, llm)
        )
    except LLMNotConfiguredError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except (EInvoiceParseError, ExtractionError, LLMExtractionError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return ExtractionResponse(
        document_id=document_id,
        method=result.method,
        input_format=result.input_format,
        document=result.document,
        usage=Usage(
            llm_calls=result.usage.calls,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            seconds=round(result.usage.seconds, 2),
        ),
    )
