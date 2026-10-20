"""Store uploaded documents and recognise what they are, without interpreting their content.

Format sniffing is deliberately byte-based (magic numbers, XML root element, PDF attachments)
and never trusts the file name or the client's content type.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from pydantic import BaseModel
from pypdf import PdfReader

from belegfluss.domain.documents import DocumentFormat

# Attachment names used by ZUGFeRD 1/2, Factur-X and XRechnung-in-PDF.
EINVOICE_ATTACHMENTS = {"factur-x.xml", "zugferd-invoice.xml", "xrechnung.xml", "zugferd.xml"}
CII_ROOT = b"CrossIndustryInvoice"
UBL_ROOT = b"urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"


class UnsupportedDocumentError(ValueError):
    """The upload is not a PDF, PNG/JPEG image or e-invoice XML."""


class StoredDocument(BaseModel):
    document_id: str
    filename: str
    format: DocumentFormat
    size_bytes: int
    sha256: str
    received_at: datetime
    embedded_einvoice: str | None = None


def _pdf_einvoice_attachment(data: bytes) -> str | None:
    try:
        reader = PdfReader(BytesIO(data))
        names = {name.lower() for name in reader.attachments}
    except Exception:  # a broken PDF is still stored; extraction will report it
        return None
    return next((n for n in sorted(names) if n in EINVOICE_ATTACHMENTS), None)


def sniff_format(data: bytes) -> tuple[DocumentFormat, str | None]:
    """Return the document format and, for hybrid PDFs, the embedded XML attachment name."""
    head = data[:2048].lstrip(b"\xef\xbb\xbf \t\r\n")
    if head.startswith(b"%PDF-"):
        attachment = _pdf_einvoice_attachment(data)
        return (DocumentFormat.ZUGFERD_PDF if attachment else DocumentFormat.PDF), attachment
    if head.startswith(b"\x89PNG\r\n\x1a\n") or head.startswith(b"\xff\xd8\xff"):
        return DocumentFormat.SCAN, None
    if head.startswith(b"<") and CII_ROOT in head:
        return DocumentFormat.XRECHNUNG_CII, None
    if head.startswith(b"<") and UBL_ROOT in head:
        return DocumentFormat.XRECHNUNG_UBL, None
    raise UnsupportedDocumentError("expected a PDF, PNG/JPEG scan or EN 16931 e-invoice XML")


class LocalDocumentStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _meta_path(self, document_id: str) -> Path:
        return self.root / f"{document_id}.json"

    def save(self, filename: str, data: bytes) -> StoredDocument:
        fmt, attachment = sniff_format(data)
        document = StoredDocument(
            document_id=str(uuid.uuid4()),
            filename=Path(filename).name or "upload",
            format=fmt,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            received_at=datetime.now(UTC),
            embedded_einvoice=attachment,
        )
        (self.root / f"{document.document_id}.bin").write_bytes(data)
        self._meta_path(document.document_id).write_text(
            document.model_dump_json(indent=2), encoding="utf-8"
        )
        return document

    def read(self, document_id: str) -> bytes | None:
        if self.get(document_id) is None:
            return None
        return (self.root / f"{document_id}.bin").read_bytes()

    def get(self, document_id: str) -> StoredDocument | None:
        try:
            uuid.UUID(document_id)
        except ValueError:
            return None
        path = self._meta_path(document_id)
        if not path.exists():
            return None
        return StoredDocument.model_validate(json.loads(path.read_text(encoding="utf-8")))
