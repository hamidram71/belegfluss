"""Plausibility checks on *extracted* documents.

The rules (rules.py) look for discrepancies in the business case. These checks look for signs
that the extraction itself went wrong, e.g. a misread order number or date on a scan. Such a
document goes to review as "extraction uncertain" instead of being processed with a silently
wrong value. They catch some misreads (those that make documents disagree), not all: a misread
invoice number, for example, stays undetected unless it collides with an existing one.
"""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum

from belegfluss.domain.models import DeliveryNote, Invoice, Model


class IssueCode(StrEnum):
    UNKNOWN_ORDER = "unknown_order"
    ORDER_MISMATCH = "order_mismatch"
    DELIVERY_NOTE_MISMATCH = "delivery_note_mismatch"
    DUE_DATE_INCONSISTENT = "due_date_inconsistent"
    ISSUE_DATE_IMPLAUSIBLE = "issue_date_implausible"
    DUPLICATE_INVOICE = "duplicate_invoice"
    EXTRACTION_WARNING = "extraction_warning"
    SUSPICIOUS_CONTENT = "suspicious_content"


class PlausibilityIssue(Model):
    code: IssueCode
    message: str


MAX_INVOICE_DELAY = timedelta(days=60)


def check_plausibility(
    invoice: Invoice,
    delivery: DeliveryNote,
    known_orders: set[str],
    seen_invoices: set[tuple[str, str]] | None = None,
    warnings: list[str] | None = None,
    security_flags: list[str] | None = None,
) -> list[PlausibilityIssue]:
    issues: list[PlausibilityIssue] = []

    def add(code: IssueCode, message: str) -> None:
        issues.append(PlausibilityIssue(code=code, message=message))

    for label, number in (("invoice", invoice.po_number), ("delivery note", delivery.po_number)):
        if number not in known_orders:
            add(IssueCode.UNKNOWN_ORDER, f"{label} refers to order {number!r}, not in the ERP")
    if invoice.po_number != delivery.po_number:
        add(
            IssueCode.ORDER_MISMATCH,
            f"invoice order {invoice.po_number!r} != delivery note order {delivery.po_number!r}",
        )
    if invoice.delivery_note_number != delivery.delivery_note_number:
        add(
            IssueCode.DELIVERY_NOTE_MISMATCH,
            f"invoice cites delivery note {invoice.delivery_note_number!r}, "
            f"document is {delivery.delivery_note_number!r}",
        )
    expected_due = invoice.issue_date + timedelta(days=invoice.payment_terms.net_days)
    if invoice.due_date != expected_due:
        add(
            IssueCode.DUE_DATE_INCONSISTENT,
            f"issue date {invoice.issue_date} + {invoice.payment_terms.net_days} days "
            f"!= due date {invoice.due_date}",
        )
    if not (
        delivery.delivery_date <= invoice.issue_date <= delivery.delivery_date + MAX_INVOICE_DELAY
    ):
        add(
            IssueCode.ISSUE_DATE_IMPLAUSIBLE,
            f"invoice date {invoice.issue_date} vs delivery date {delivery.delivery_date}",
        )
    if seen_invoices is not None:
        key = (invoice.seller.party_id, invoice.invoice_number)
        if key in seen_invoices:
            add(IssueCode.DUPLICATE_INVOICE, f"invoice {invoice.invoice_number} already processed")
        seen_invoices.add(key)
    for warning in warnings or []:
        add(IssueCode.EXTRACTION_WARNING, warning)
    for flag in security_flags or []:
        add(IssueCode.SUSPICIOUS_CONTENT, flag)
    return issues
