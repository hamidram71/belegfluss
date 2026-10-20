"""Rule-based three-way match against purchase order, delivery note and ERP master data.

What rules can decide on their own:
* arithmetic, VAT rates, bank details, quantities, unordered items, payment terms.

What they cannot decide: *why* a price deviates. The purchase order carries the contract price
(including any volume discount), so a higher invoice price is detected here, but telling
"price above contract" from "volume discount not applied" and citing the clause needs the
contract text. Rules therefore report ``PRICE_ABOVE_CONTRACT`` with
``needs_contract_review``; the agent (delivery 3) classifies it using RAG over the contract.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from belegfluss.domain.discrepancies import Decision, Discrepancy, DiscrepancyType
from belegfluss.domain.identifiers import is_valid_iban
from belegfluss.domain.models import DeliveryNote, Invoice, PurchaseOrder
from belegfluss.domain.money import format_unit_price_de
from belegfluss.master_data import MasterData

NEEDS_CONTRACT_REVIEW = "needs_contract_review"


def run_rules(
    invoice: Invoice,
    order: PurchaseOrder,
    delivery: DeliveryNote,
    master: MasterData,
) -> list[Discrepancy]:
    findings: list[Discrepancy] = []

    # Arithmetic (BR-CO-10 .. BR-CO-15 in EN 16931 terms).
    computed, stated = invoice.computed_totals(), invoice.stated_totals
    if computed != stated:
        findings.append(
            Discrepancy(
                type=DiscrepancyType.TOTALS_INCONSISTENT,
                expected=str(computed.gross),
                actual=str(stated.gross),
                note=f"computed net/VAT/gross {computed.net}/{computed.vat}/{computed.gross}, "
                f"stated {stated.net}/{stated.vat}/{stated.gross}",
            )
        )

    # Bank details and payment terms against the vendor master record (never the invoice).
    record = master.supplier(invoice.seller.party_id) or master.resolve_supplier(
        invoice.seller.vat_id, invoice.seller.name
    )
    if record is None:
        findings.append(
            Discrepancy(
                type=DiscrepancyType.BANK_DETAILS_CHANGED,
                actual=invoice.seller.iban,
                note="supplier not found in master data; bank details cannot be verified",
            )
        )
    else:
        iban = invoice.seller.iban or ""
        if iban.replace(" ", "") != (record.party.iban or ""):
            findings.append(
                Discrepancy(
                    type=DiscrepancyType.BANK_DETAILS_CHANGED,
                    expected=record.party.iban,
                    actual=iban or None,
                    note=None if is_valid_iban(iban) else "IBAN on invoice fails the checksum",
                )
            )
        if invoice.payment_terms != record.payment_terms:
            findings.append(
                Discrepancy(
                    type=DiscrepancyType.PAYMENT_TERMS_DEVIATION,
                    expected=record.payment_terms.describe_de(),
                    actual=invoice.payment_terms.describe_de(),
                )
            )

    ordered = {item.sku: item for item in order.items}
    delivered: dict[str, Decimal] = defaultdict(Decimal)
    for d in delivery.items:
        delivered[d.sku] += d.quantity
    invoiced: dict[str, Decimal] = defaultdict(Decimal)

    for item in invoice.items:
        product = master.product(item.sku)
        if product is not None and item.vat_rate != product.vat_rate:
            findings.append(
                Discrepancy(
                    type=DiscrepancyType.WRONG_VAT_RATE,
                    position=item.position,
                    sku=item.sku,
                    expected=str(product.vat_rate),
                    actual=str(item.vat_rate),
                )
            )
        order_line = ordered.get(item.sku)
        if order_line is None:
            findings.append(
                Discrepancy(
                    type=DiscrepancyType.ITEM_NOT_ORDERED,
                    position=item.position,
                    sku=item.sku or None,
                    actual=f"{item.quantity} x {format_unit_price_de(item.unit_price)}",
                    note=item.description,
                )
            )
            continue
        invoiced[item.sku] += item.quantity
        if item.unit_price > order_line.unit_price:
            findings.append(
                Discrepancy(
                    type=DiscrepancyType.PRICE_ABOVE_CONTRACT,
                    position=item.position,
                    sku=item.sku,
                    expected=str(order_line.unit_price),
                    actual=str(item.unit_price),
                    note=NEEDS_CONTRACT_REVIEW,
                )
            )

    for item in invoice.items:
        if item.sku in ordered and invoiced[item.sku] > delivered[item.sku]:
            findings.append(
                Discrepancy(
                    type=DiscrepancyType.QUANTITY_EXCEEDS_DELIVERY,
                    position=item.position,
                    sku=item.sku,
                    expected=str(delivered[item.sku]),
                    actual=str(invoiced[item.sku]),
                )
            )
            invoiced[item.sku] = Decimal("-1")  # report each article once
    return findings


def decide(findings: list[Discrepancy]) -> Decision:
    return Decision.REVIEW if findings else Decision.APPROVE
