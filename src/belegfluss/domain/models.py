"""Pydantic models for the documents of a German B2B purchase-to-pay process.

The four document types that Belegfluss reconciles:

* ``FrameworkContract`` (Rahmenvertrag): agreed prices, volume discount and payment terms.
* ``PurchaseOrder`` (Bestellung): what the buyer ordered, exported from the buyer's ERP.
* ``DeliveryNote`` (Lieferschein): what the supplier actually delivered.
* ``Invoice`` (Rechnung): what the supplier bills.

Invoices carry their *stated* totals separately from line items, because a real invoice can
contain arithmetic errors. Validation compares stated totals with ``computed_totals()``
instead of trusting either one (see docs/adr/0003).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from belegfluss.domain.money import percent_of, to_money, to_unit_price


class Model(BaseModel):
    """Base model: immutable, no unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class UnitCode(StrEnum):
    """UN/ECE Recommendation 20 unit codes, as required by EN 16931."""

    PIECE = "H87"
    SET = "SET"
    METRE = "MTR"
    KILOGRAM = "KGM"
    LITRE = "LTR"

    @property
    def label_de(self) -> str:
        return {
            UnitCode.PIECE: "Stk",
            UnitCode.SET: "Satz",
            UnitCode.METRE: "m",
            UnitCode.KILOGRAM: "kg",
            UnitCode.LITRE: "l",
        }[self]


class Address(Model):
    street: str
    postal_code: str
    city: str
    country_code: str = "DE"


class Party(Model):
    """A company taking part in the process (buyer or supplier)."""

    party_id: str = Field(description="Internal master-data key, e.g. a creditor number.")
    name: str
    address: Address
    vat_id: str | None = None
    iban: str | None = None
    bic: str | None = None
    email: str | None = None


class PaymentTerms(Model):
    net_days: int = Field(gt=0)
    skonto_percent: Decimal | None = None
    skonto_days: int | None = None

    def describe_de(self) -> str:
        """Human-readable German payment terms as printed on documents."""
        text = f"Zahlbar innerhalb von {self.net_days} Tagen netto"
        if self.skonto_percent and self.skonto_days:
            rate = format(self.skonto_percent.normalize(), "f").replace(".", ",")
            text += f", bei Zahlung innerhalb von {self.skonto_days} Tagen {rate} % Skonto"
        return text + "."


class LineItem(Model):
    """A priced line, used on purchase orders and invoices."""

    position: int = Field(ge=1)
    sku: str
    description: str
    quantity: Decimal = Field(gt=0)
    unit: UnitCode
    unit_price: Decimal = Field(ge=0, description="Net unit price in EUR.")
    vat_rate: Decimal = Field(default=Decimal("19"), description="VAT rate in percent.")

    @property
    def net_amount(self) -> Decimal:
        """Line net amount (BT-131). Derived, so it is never stored and cannot drift."""
        return to_money(self.quantity * self.unit_price)


class DeliveryItem(Model):
    """A line on a delivery note: quantities only, no prices."""

    position: int = Field(ge=1)
    sku: str
    description: str
    quantity: Decimal = Field(gt=0)
    unit: UnitCode


class ContractClause(Model):
    clause_id: str = Field(description="Clause reference as printed, e.g. '§ 4' or 'Anlage 1'.")
    title: str
    text: str


class PriceAgreement(Model):
    sku: str
    description: str
    unit: UnitCode
    unit_price: Decimal


class VolumeDiscount(Model):
    """Extra discount per position once the ordered quantity reaches a threshold."""

    min_quantity: Decimal
    percent: Decimal
    clause_id: str


class FrameworkContract(Model):
    contract_number: str
    supplier: Party
    buyer: Party
    valid_from: date
    valid_to: date
    price_agreements: list[PriceAgreement]
    volume_discount: VolumeDiscount | None = None
    payment_terms: PaymentTerms
    price_list_clause_id: str
    payment_terms_clause_id: str
    partial_delivery_clause_id: str
    bank_details_clause_id: str
    clauses: list[ContractClause]

    def price_for(self, sku: str) -> PriceAgreement | None:
        return next((p for p in self.price_agreements if p.sku == sku), None)

    def agreed_unit_price(self, sku: str, quantity: Decimal) -> Decimal | None:
        """Contract price for ``quantity`` units, including the volume discount if it applies."""
        agreement = self.price_for(sku)
        if agreement is None:
            return None
        price = agreement.unit_price
        if self.volume_discount and quantity >= self.volume_discount.min_quantity:
            price = to_unit_price(price * (Decimal(100) - self.volume_discount.percent) / 100)
        return price


class PurchaseOrder(Model):
    po_number: str
    order_date: date
    buyer: Party
    supplier: Party
    contract_number: str | None
    items: list[LineItem]


class DeliveryNote(Model):
    delivery_note_number: str
    delivery_date: date
    po_number: str
    supplier: Party
    buyer: Party
    items: list[DeliveryItem]


class InvoiceTotals(Model):
    net: Decimal
    vat: Decimal
    gross: Decimal


class VatBreakdownLine(Model):
    rate: Decimal
    basis: Decimal
    amount: Decimal


class Invoice(Model):
    invoice_number: str
    issue_date: date
    due_date: date
    seller: Party
    buyer: Party
    po_number: str
    delivery_note_number: str
    contract_number: str | None
    items: list[LineItem]
    payment_terms: PaymentTerms
    stated_totals: InvoiceTotals = Field(description="Totals as printed on the document.")

    def vat_breakdown(self) -> list[VatBreakdownLine]:
        """VAT per rate, calculated on the summed net amounts per rate (EN 16931 BG-23)."""
        basis: dict[Decimal, Decimal] = defaultdict(Decimal)
        for item in self.items:
            basis[item.vat_rate] += item.net_amount
        return [
            VatBreakdownLine(rate=rate, basis=to_money(base), amount=percent_of(base, rate))
            for rate, base in sorted(basis.items())
        ]

    def computed_totals(self) -> InvoiceTotals:
        breakdown = self.vat_breakdown()
        net = to_money(sum((line.basis for line in breakdown), Decimal(0)))
        vat = to_money(sum((line.amount for line in breakdown), Decimal(0)))
        return InvoiceTotals(net=net, vat=vat, gross=net + vat)
