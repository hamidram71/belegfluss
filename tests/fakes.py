"""Test doubles for the LLM, so the suite never calls a real API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from belegfluss.domain.models import DeliveryNote, Invoice, Party
from belegfluss.domain.money import format_decimal_de
from belegfluss.extraction.llm import LLMResult, LLMUsage
from belegfluss.extraction.schemas import (
    ExtractedDeliveryNote,
    ExtractedInvoice,
    ExtractedLine,
    ExtractedParty,
)


class FakeLLM:
    model = "fake-model"

    def __init__(self, responses: list[BaseModel]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def extract[M: BaseModel](
        self,
        schema: type[M],
        instructions: str,
        text: str | None = None,
        images: list[bytes] | None = None,
    ) -> LLMResult[M]:
        self.calls.append(
            {"schema": schema, "instructions": instructions, "text": text, "images": images}
        )
        response = self.responses.pop(0)
        assert isinstance(response, schema)
        return LLMResult(parsed=response, usage=LLMUsage(1, 1200, 300, 0.5))


def _party(party: Party, with_vat: bool = True) -> ExtractedParty:
    return ExtractedParty(
        name=party.name,
        street=party.address.street,
        postal_code=party.address.postal_code,
        city=party.address.city,
        vat_id=party.vat_id if with_vat else None,
        iban=party.iban,
    )


def transcribe_invoice(invoice: Invoice, german_numbers: bool = False) -> ExtractedInvoice:
    """What a perfect model would return; optionally with German number formatting."""

    def num(value: object) -> str:
        return format_decimal_de(value) if german_numbers else str(value)  # type: ignore[arg-type]

    return ExtractedInvoice(
        invoice_number=invoice.invoice_number,
        issue_date=invoice.issue_date.isoformat(),
        due_date=invoice.due_date.isoformat(),
        seller=_party(invoice.seller),
        buyer=_party(invoice.buyer, with_vat=False),
        po_number=invoice.po_number,
        delivery_note_number=invoice.delivery_note_number,
        contract_number=invoice.contract_number,
        lines=[
            ExtractedLine(
                position=str(i.position),
                sku=i.sku,
                description=i.description,
                quantity=num(i.quantity),
                unit=i.unit.label_de,
                unit_price=num(i.unit_price),
                vat_rate=num(i.vat_rate),
            )
            for i in invoice.items
        ],
        payment_terms_text=invoice.payment_terms.describe_de(),
        total_net=num(invoice.stated_totals.net),
        total_vat=num(invoice.stated_totals.vat),
        total_gross=num(invoice.stated_totals.gross),
    )


def transcribe_delivery_note(note: DeliveryNote) -> ExtractedDeliveryNote:
    return ExtractedDeliveryNote(
        delivery_note_number=note.delivery_note_number,
        delivery_date=note.delivery_date.isoformat(),
        po_number=note.po_number,
        supplier=_party(note.supplier),
        buyer=_party(note.buyer, with_vat=False),
        lines=[
            ExtractedLine(
                position=str(i.position),
                sku=i.sku,
                description=i.description,
                quantity=str(i.quantity),
                unit=i.unit.label_de,
                unit_price=None,
                vat_rate=None,
            )
            for i in note.items
        ],
    )
