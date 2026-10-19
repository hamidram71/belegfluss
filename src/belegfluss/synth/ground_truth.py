"""Ground-truth records written next to (never inside) the generated documents."""

from __future__ import annotations

from pydantic import Field

from belegfluss.domain.discrepancies import Decision, Discrepancy
from belegfluss.domain.documents import DocumentFormat, DocumentKind
from belegfluss.domain.models import DeliveryNote, Invoice, Model, PurchaseOrder


class DocumentRef(Model):
    kind: DocumentKind
    format: DocumentFormat
    path: str = Field(description="Path relative to the dataset root.")


class GroundTruthSet(Model):
    set_id: str
    supplier_id: str
    contract_number: str | None
    documents: list[DocumentRef]
    purchase_order: PurchaseOrder
    delivery_note: DeliveryNote
    invoice: Invoice
    discrepancies: list[Discrepancy]
    decision: Decision
    variations: list[str] = Field(
        description="Legitimate deviations that must NOT be flagged, e.g. partial_delivery."
    )


class Manifest(Model):
    generator_version: str
    seed: int
    n_sets: int
    n_suppliers: int
    p_discrepant: float
    decisions: dict[str, int]
    discrepancy_counts: dict[str, int]
    invoice_formats: dict[str, int]
    delivery_note_formats: dict[str, int]
    variations: dict[str, int]
