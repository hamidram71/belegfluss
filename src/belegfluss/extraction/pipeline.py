"""Route a document to the right extraction path (ADR 0001: XML first, LLM only if needed)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from belegfluss.domain.documents import DocumentFormat
from belegfluss.domain.models import DeliveryNote, Invoice
from belegfluss.extraction.cii import EInvoiceParseError, embedded_xml, parse_cii
from belegfluss.extraction.llm import LLMNotConfiguredError, LLMUsage, StructuredLLM
from belegfluss.extraction.llm_extract import extract_delivery_note_llm, extract_invoice_llm
from belegfluss.master_data import MasterData
from belegfluss.security.screening import screen_pdf
from belegfluss.storage.documents import sniff_format


class ExtractionMethod(StrEnum):
    CII_XML = "cii_xml"
    ZUGFERD_EMBEDDED_XML = "zugferd_embedded_xml"
    LLM_TEXT = "llm_text"
    LLM_VISION = "llm_vision"


@dataclass
class Extracted[D: (Invoice, DeliveryNote)]:
    document: D
    method: ExtractionMethod
    input_format: DocumentFormat
    usage: LLMUsage = field(default_factory=LLMUsage)
    warnings: list[str] = field(default_factory=list)
    security_flags: list[str] = field(default_factory=list)


def _require(llm: StructuredLLM | None) -> StructuredLLM:
    if llm is None:
        raise LLMNotConfiguredError(
            "This document has no structured e-invoice data and needs an LLM. "
            "Set BELEGFLUSS_LLM_MODEL and the API key."
        )
    return llm


def _screen(data: bytes, fmt: DocumentFormat) -> list[str]:
    """Screen every PDF, also hybrid ones whose XML is used: hidden instructions in the visual
    part are a red flag about the sender even if no model reads them (ADR 0009)."""
    if fmt not in (DocumentFormat.PDF, DocumentFormat.ZUGFERD_PDF):
        return []
    return [f"{f.code}: {f.detail}" for f in screen_pdf(data)]


def extract_invoice(
    data: bytes, master: MasterData, llm: StructuredLLM | None
) -> Extracted[Invoice]:
    fmt, _ = sniff_format(data)
    result = _extract_invoice(data, fmt, master, llm)
    result.security_flags = _screen(data, fmt)
    return result


def _extract_invoice(
    data: bytes, fmt: DocumentFormat, master: MasterData, llm: StructuredLLM | None
) -> Extracted[Invoice]:
    if fmt is DocumentFormat.XRECHNUNG_CII:
        return Extracted(parse_cii(data, master), ExtractionMethod.CII_XML, fmt)
    if fmt is DocumentFormat.XRECHNUNG_UBL:
        raise EInvoiceParseError("UBL syntax is recognised but not parsed yet; CII only")
    if fmt is DocumentFormat.ZUGFERD_PDF:
        return Extracted(
            parse_cii(embedded_xml(data), master), ExtractionMethod.ZUGFERD_EMBEDDED_XML, fmt
        )
    invoice, result, vision, warnings = extract_invoice_llm(
        data, fmt is DocumentFormat.PDF, _require(llm), master
    )
    method = ExtractionMethod.LLM_VISION if vision else ExtractionMethod.LLM_TEXT
    return Extracted(invoice, method, fmt, result.usage, warnings)


def extract_delivery_note(
    data: bytes, master: MasterData, llm: StructuredLLM | None
) -> Extracted[DeliveryNote]:
    fmt, _ = sniff_format(data)
    flags = _screen(data, fmt)
    if fmt not in (DocumentFormat.PDF, DocumentFormat.SCAN):
        raise ValueError(f"unexpected delivery note format: {fmt}")
    note, result, vision, warnings = extract_delivery_note_llm(
        data, fmt is DocumentFormat.PDF, _require(llm), master
    )
    method = ExtractionMethod.LLM_VISION if vision else ExtractionMethod.LLM_TEXT
    return Extracted(note, method, fmt, result.usage, warnings, flags)
