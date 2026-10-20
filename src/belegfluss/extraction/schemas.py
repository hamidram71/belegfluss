"""Output schemas for LLM extraction (OpenAI structured outputs).

They are deliberately separate from the domain models: the LLM returns every number as a
string exactly as printed, and conversion to Decimal happens in our code, where it can be
validated and tested. Every field is required (nullable instead of optional), as strict
structured outputs require.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExtractedParty(_Schema):
    name: str = Field(description="Company name as printed.")
    street: str | None
    postal_code: str | None
    city: str | None
    vat_id: str | None = Field(description="USt-IdNr., e.g. DE123456789, without spaces.")
    iban: str | None = Field(description="IBAN without spaces, if printed for this party.")


class ExtractedLine(_Schema):
    position: str | None = Field(description="Position number (Pos.) as printed.")
    sku: str | None = Field(description="Article number (Art.-Nr.) as printed.")
    description: str
    quantity: str = Field(description="Quantity as plain decimal, e.g. '1000' or '12.5'.")
    unit: str | None = Field(description="Unit as printed, e.g. 'Stk', 'm', 'kg'.")
    unit_price: str | None = Field(description="Net unit price as plain decimal, e.g. '0.2844'.")
    vat_rate: str | None = Field(description="VAT rate in percent as plain decimal, e.g. '19'.")


class ExtractedInvoice(_Schema):
    invoice_number: str
    issue_date: str = Field(description="Invoice date, ISO YYYY-MM-DD.")
    due_date: str | None = Field(description="Due date, ISO YYYY-MM-DD, if printed.")
    seller: ExtractedParty
    buyer: ExtractedParty
    po_number: str | None = Field(description="Buyer's order number (Bestellnummer).")
    delivery_note_number: str | None = Field(description="Lieferschein number referenced.")
    contract_number: str | None = Field(description="Framework contract number (Rahmenvertrag).")
    lines: list[ExtractedLine]
    payment_terms_text: str | None = Field(description="Payment terms sentence as printed.")
    total_net: str = Field(description="Net total as printed, plain decimal.")
    total_vat: str = Field(description="VAT total as printed (sum if several rates).")
    total_gross: str = Field(description="Gross total (Rechnungsbetrag) as printed.")


class ExtractedDeliveryNote(_Schema):
    delivery_note_number: str
    delivery_date: str = Field(description="Delivery date, ISO YYYY-MM-DD.")
    po_number: str | None
    supplier: ExtractedParty
    buyer: ExtractedParty
    lines: list[ExtractedLine]
