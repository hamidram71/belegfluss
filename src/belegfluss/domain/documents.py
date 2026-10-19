"""Document kinds and file formats handled by Belegfluss."""

from enum import StrEnum


class DocumentKind(StrEnum):
    INVOICE = "invoice"
    DELIVERY_NOTE = "delivery_note"
    PURCHASE_ORDER = "purchase_order"
    CONTRACT = "contract"


class DocumentFormat(StrEnum):
    XRECHNUNG_CII = "xrechnung_cii"
    """Structured e-invoice: XRechnung profile of EN 16931 in UN/CEFACT CII syntax."""

    XRECHNUNG_UBL = "xrechnung_ubl"
    """Structured e-invoice in OASIS UBL syntax (recognised on intake; parsing in week 2)."""

    ZUGFERD_PDF = "zugferd_pdf"
    """Hybrid e-invoice: human-readable PDF with embedded EN 16931 CII XML."""

    PDF = "pdf"
    """Digital PDF without structured data."""

    SCAN = "scan_png"
    """Image of a paper document, with scan artefacts."""

    ERP_JSON = "erp_json"
    """Structured export from the buyer's ERP system."""
