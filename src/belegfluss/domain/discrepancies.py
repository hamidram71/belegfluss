"""Discrepancy taxonomy: everything Belegfluss must detect when matching documents.

The same types label the synthetic ground truth and, from week 3 on, the agent's findings.
Using one shared vocabulary makes evaluation a simple comparison of sets.
"""

from enum import StrEnum

from pydantic import Field

from belegfluss.domain.models import Model


class DiscrepancyType(StrEnum):
    PRICE_ABOVE_CONTRACT = "price_above_contract"
    """Invoiced unit price is higher than the framework contract price."""

    VOLUME_DISCOUNT_MISSING = "volume_discount_missing"
    """Quantity qualifies for the contract's volume discount, but it was not applied."""

    QUANTITY_EXCEEDS_DELIVERY = "quantity_exceeds_delivery"
    """More units invoiced than the delivery note confirms."""

    ITEM_NOT_ORDERED = "item_not_ordered"
    """Invoice line without a matching purchase order position."""

    WRONG_VAT_RATE = "wrong_vat_rate"
    """VAT rate on a line does not match the rate for that product (7 % vs 19 %)."""

    TOTALS_INCONSISTENT = "totals_inconsistent"
    """Stated invoice totals do not add up to the line items."""

    PAYMENT_TERMS_DEVIATION = "payment_terms_deviation"
    """Payment terms on the invoice are worse for the buyer than the contract terms."""

    BANK_DETAILS_CHANGED = "bank_details_changed"
    """IBAN on the invoice differs from supplier master data (classic payment fraud pattern)."""


class Decision(StrEnum):
    APPROVE = "approve"
    REVIEW = "review"


class Discrepancy(Model):
    type: DiscrepancyType
    position: int | None = Field(default=None, description="Invoice line position, if any.")
    sku: str | None = None
    expected: str | None = None
    actual: str | None = None
    clause_id: str | None = Field(
        default=None, description="Contract clause that justifies the expectation, for RAG eval."
    )
    note: str | None = None
