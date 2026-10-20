"""Build labeled document sets: purchase order, delivery note and invoice per purchase.

Each set starts as a *correct* purchase-to-pay case. Some sets also get legitimate variations
that a naive matcher would wrongly flag (partial deliveries, items without contract price,
supplier-specific wording). Then, with probability ``p_discrepant``, one or two discrepancies
from the taxonomy are injected into the invoice and recorded as ground truth.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from belegfluss.domain.discrepancies import Decision, Discrepancy, DiscrepancyType
from belegfluss.domain.models import (
    DeliveryItem,
    DeliveryNote,
    Invoice,
    InvoiceTotals,
    LineItem,
    Party,
    PaymentTerms,
    PurchaseOrder,
    UnitCode,
)
from belegfluss.domain.money import format_unit_price_de, to_unit_price
from belegfluss.synth.catalog import by_sku
from belegfluss.synth.world import Supplier, World, ascii_slug, new_iban

ORDER_PERIOD_START = date(2026, 3, 2)
ORDER_PERIOD_DAYS = 200


@dataclass
class DraftSet:
    """Mutable working state while a set is generated."""

    set_id: str
    supplier: Supplier
    purchase_order: PurchaseOrder
    delivery_note: DeliveryNote
    invoice_items: list[LineItem]
    invoice_terms: PaymentTerms
    invoice_iban: str
    stated_totals_override: InvoiceTotals | None = None
    discrepancies: list[Discrepancy] = field(default_factory=list)
    variations: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GeneratedSet:
    set_id: str
    supplier: Supplier
    purchase_order: PurchaseOrder
    delivery_note: DeliveryNote
    invoice: Invoice
    discrepancies: list[Discrepancy]
    variations: list[str]

    @property
    def decision(self) -> Decision:
        return Decision.REVIEW if self.discrepancies else Decision.APPROVE


def _quantity_for(price: Decimal, rng: random.Random) -> Decimal:
    if price < Decimal("1"):
        return Decimal(rng.choice([100, 200, 250, 500, 1000]))
    if price < Decimal("15"):
        return Decimal(rng.choice([10, 20, 25, 50, 100, 150]))
    if price < Decimal("60"):
        return Decimal(rng.randint(2, 30))
    return Decimal(rng.randint(1, 6))


_ABBREVIATIONS = (
    ("Sechskantschraube", "6kt-Schraube"),
    ("Sechskantmutter", "6kt-Mutter"),
    ("Rillenkugellager", "RKL"),
    ("Pneumatikzylinder", "Pneu-Zylinder"),
    ("Näherungsschalter", "Näh.-Schalter"),
    ("verzinkt", "vz."),
)


def _supplier_wording(description: str, rng: random.Random) -> str:
    """Suppliers describe the same article in their own words; matching must survive that."""
    text = description
    for long, short in _ABBREVIATIONS:
        text = text.replace(long, short)
    if text == description:
        text = description.split(",")[0]
    return text.upper() if rng.random() < 0.3 else text


def _build_order(
    rng: random.Random, world: World, supplier: Supplier, number: int, order_date: date
) -> tuple[PurchaseOrder, list[str]]:
    contract = supplier.contract
    variations: list[str] = []
    covered = [by_sku(a.sku) for a in contract.price_agreements]
    chosen = rng.sample(covered, k=min(len(covered), rng.randint(2, 5)))
    uncovered = [i for i in supplier.assortment if contract.price_for(i.sku) is None]
    if uncovered and rng.random() < 0.25:
        chosen.append(rng.choice(uncovered))
        variations.append("off_contract_item")
    items = []
    for position, catalog_item in enumerate(chosen, start=1):
        quantity = _quantity_for(catalog_item.list_price, rng)
        price = contract.agreed_unit_price(catalog_item.sku, quantity)
        items.append(
            LineItem(
                position=position,
                sku=catalog_item.sku,
                description=catalog_item.description,
                quantity=quantity,
                unit=catalog_item.unit,
                unit_price=price if price is not None else catalog_item.list_price,
                vat_rate=catalog_item.vat_rate,
            )
        )
    if contract.volume_discount and any(
        i.quantity >= contract.volume_discount.min_quantity
        and contract.price_for(i.sku) is not None
        for i in items
    ):
        variations.append("volume_discount_applies")
    order = PurchaseOrder(
        po_number=f"BE-2026-{number:05d}",
        order_date=order_date,
        buyer=world.buyer,
        supplier=supplier.party,
        contract_number=contract.contract_number,
        items=items,
    )
    return order, variations


def _build_delivery(
    rng: random.Random, order: PurchaseOrder, number: int, delivery_date: date
) -> tuple[DeliveryNote, list[str]]:
    variations: list[str] = []
    items = []
    partial_position = rng.choice(order.items).position if rng.random() < 0.15 else None
    for item in order.items:
        quantity = item.quantity
        if item.position == partial_position and quantity > 1:
            reduced = (quantity * Decimal(rng.choice(["0.5", "0.8"]))).quantize(Decimal(1))
            quantity = max(Decimal(1), reduced)
            variations.append("partial_delivery")
        items.append(
            DeliveryItem(
                position=item.position,
                sku=item.sku,
                description=item.description,
                quantity=quantity,
                unit=item.unit,
            )
        )
    prefix = (ascii_slug(order.supplier.name)[:3] or "lsx").upper()
    note = DeliveryNote(
        delivery_note_number=f"LS-{prefix}-{number:06d}",
        delivery_date=delivery_date,
        po_number=order.po_number,
        supplier=order.supplier,
        buyer=order.buyer,
        items=items,
    )
    return note, variations


def _initial_invoice_items(
    rng: random.Random, order: PurchaseOrder, delivery: DeliveryNote
) -> tuple[list[LineItem], list[str]]:
    delivered = {d.sku: d.quantity for d in delivery.items}
    items = []
    reworded = False
    for item in order.items:
        description = item.description
        if rng.random() < 0.35:
            description = _supplier_wording(description, rng)
            reworded = True
        items.append(
            item.model_copy(update={"quantity": delivered[item.sku], "description": description})
        )
    return items, (["supplier_wording"] if reworded else [])


# --- Discrepancy injectors -------------------------------------------------------------
# Each injector mutates the draft and returns True, or returns False if not applicable.

Injector = Callable[[DraftSet, random.Random], bool]


def _ordered_lines(draft: DraftSet) -> list[LineItem]:
    """Invoice lines that correspond to purchase order positions.

    Injectors that reason about ordered or delivered quantities must ignore lines added by an
    earlier injector (``ITEM_NOT_ORDERED``), otherwise two combined discrepancies interfere.
    """
    ordered = {o.sku for o in draft.purchase_order.items}
    return [i for i in draft.invoice_items if i.sku in ordered]


def _price_free_lines(draft: DraftSet) -> list[LineItem]:
    """Ordered lines without a price discrepancy yet. Two price errors on one line would
    overwrite each other and leave a stale label in the ground truth."""
    taken = {
        d.position
        for d in draft.discrepancies
        if d.type in (DiscrepancyType.PRICE_ABOVE_CONTRACT, DiscrepancyType.VOLUME_DISCOUNT_MISSING)
    }
    return [i for i in _ordered_lines(draft) if i.position not in taken]


def _replace_item(draft: DraftSet, position: int, **update: object) -> None:
    draft.invoice_items = [
        i.model_copy(update=update) if i.position == position else i for i in draft.invoice_items
    ]


def _inject_price_above_contract(draft: DraftSet, rng: random.Random) -> bool:
    contract = draft.supplier.contract
    candidates = [i for i in _price_free_lines(draft) if contract.price_for(i.sku) is not None]
    if not candidates:
        return False
    item = rng.choice(candidates)
    ordered = next(o for o in draft.purchase_order.items if o.sku == item.sku)
    expected = contract.agreed_unit_price(item.sku, ordered.quantity)
    assert expected is not None
    raised = to_unit_price(expected * Decimal(str(1 + rng.uniform(0.03, 0.12))))
    if raised <= expected:
        raised = expected + (Decimal("0.0001") if expected < 1 else Decimal("0.01"))
    _replace_item(draft, item.position, unit_price=raised)
    draft.discrepancies.append(
        Discrepancy(
            type=DiscrepancyType.PRICE_ABOVE_CONTRACT,
            position=item.position,
            sku=item.sku,
            expected=str(expected),
            actual=str(raised),
            clause_id=contract.price_list_clause_id,
        )
    )
    return True


def _inject_volume_discount_missing(draft: DraftSet, rng: random.Random) -> bool:
    contract = draft.supplier.contract
    discount = contract.volume_discount
    if discount is None:
        return False
    ordered = {o.sku: o.quantity for o in draft.purchase_order.items}
    candidates = [
        i
        for i in _price_free_lines(draft)
        if contract.price_for(i.sku) is not None and ordered[i.sku] >= discount.min_quantity
    ]
    if not candidates:
        return False
    item = rng.choice(candidates)
    agreement = contract.price_for(item.sku)
    assert agreement is not None
    expected = contract.agreed_unit_price(item.sku, ordered[item.sku])
    if expected is None or expected == agreement.unit_price:
        return False
    _replace_item(draft, item.position, unit_price=agreement.unit_price)
    draft.discrepancies.append(
        Discrepancy(
            type=DiscrepancyType.VOLUME_DISCOUNT_MISSING,
            position=item.position,
            sku=item.sku,
            expected=str(expected),
            actual=str(agreement.unit_price),
            clause_id=discount.clause_id,
        )
    )
    return True


def _inject_quantity_exceeds_delivery(draft: DraftSet, rng: random.Random) -> bool:
    item = rng.choice(_ordered_lines(draft))
    delivered = next(d.quantity for d in draft.delivery_note.items if d.sku == item.sku)
    share = Decimal(str(round(rng.uniform(0.05, 0.25), 3)))
    extra = max(Decimal(1), (delivered * share).quantize(Decimal(1)))
    _replace_item(draft, item.position, quantity=delivered + extra)
    draft.discrepancies.append(
        Discrepancy(
            type=DiscrepancyType.QUANTITY_EXCEEDS_DELIVERY,
            position=item.position,
            sku=item.sku,
            expected=str(delivered),
            actual=str(delivered + extra),
            clause_id=draft.supplier.contract.partial_delivery_clause_id,
        )
    )
    return True


def _inject_item_not_ordered(draft: DraftSet, rng: random.Random) -> bool:
    ordered_skus = {i.sku for i in draft.purchase_order.items}
    position = max(i.position for i in draft.invoice_items) + 1
    others = [i for i in draft.supplier.assortment if i.sku not in ordered_skus]
    if others and rng.random() < 0.5:
        extra = rng.choice(others)
        line = LineItem(
            position=position,
            sku=extra.sku,
            description=extra.description,
            quantity=_quantity_for(extra.list_price, rng),
            unit=extra.unit,
            unit_price=extra.list_price,
            vat_rate=extra.vat_rate,
        )
        note = "Artikel wurde nicht bestellt."
    else:
        line = LineItem(
            position=position,
            sku="VERS-PAUSCH",
            description="Fracht- und Verpackungspauschale",
            quantity=Decimal(1),
            unit=UnitCode.PIECE,
            unit_price=Decimal(rng.choice(["19.50", "24.90", "35.00", "49.00"])),
        )
        note = "Pauschale ohne vertragliche Vereinbarung."
    draft.invoice_items.append(line)
    draft.discrepancies.append(
        Discrepancy(
            type=DiscrepancyType.ITEM_NOT_ORDERED,
            position=position,
            sku=line.sku,
            expected=None,
            actual=f"{line.quantity} x {format_unit_price_de(line.unit_price)}",
            clause_id="§ 3" if line.sku == "VERS-PAUSCH" else None,
            note=note,
        )
    )
    return True


def _inject_wrong_vat_rate(draft: DraftSet, rng: random.Random) -> bool:
    item = rng.choice(_ordered_lines(draft))
    wrong = Decimal("7") if item.vat_rate == Decimal("19") else Decimal("19")
    _replace_item(draft, item.position, vat_rate=wrong)
    draft.discrepancies.append(
        Discrepancy(
            type=DiscrepancyType.WRONG_VAT_RATE,
            position=item.position,
            sku=item.sku,
            expected=str(item.vat_rate),
            actual=str(wrong),
        )
    )
    return True


def _inject_payment_terms_deviation(draft: DraftSet, rng: random.Random) -> bool:
    agreed = draft.supplier.contract.payment_terms
    if agreed.skonto_percent:
        worse = PaymentTerms(net_days=agreed.net_days)
    else:
        worse = PaymentTerms(net_days=rng.choice([7, 10, 14]))
        if worse.net_days >= agreed.net_days:
            return False
    draft.invoice_terms = worse
    draft.discrepancies.append(
        Discrepancy(
            type=DiscrepancyType.PAYMENT_TERMS_DEVIATION,
            expected=agreed.describe_de(),
            actual=worse.describe_de(),
            clause_id=draft.supplier.contract.payment_terms_clause_id,
        )
    )
    return True


def _inject_bank_details_changed(draft: DraftSet, rng: random.Random) -> bool:
    master_iban = draft.supplier.party.iban
    draft.invoice_iban = new_iban(rng)
    draft.discrepancies.append(
        Discrepancy(
            type=DiscrepancyType.BANK_DETAILS_CHANGED,
            expected=master_iban,
            actual=draft.invoice_iban,
            clause_id=draft.supplier.contract.bank_details_clause_id,
            note="Gültige IBAN, aber abweichend von den Lieferantenstammdaten.",
        )
    )
    return True


INJECTORS: dict[DiscrepancyType, Injector] = {
    DiscrepancyType.PRICE_ABOVE_CONTRACT: _inject_price_above_contract,
    DiscrepancyType.VOLUME_DISCOUNT_MISSING: _inject_volume_discount_missing,
    DiscrepancyType.QUANTITY_EXCEEDS_DELIVERY: _inject_quantity_exceeds_delivery,
    DiscrepancyType.ITEM_NOT_ORDERED: _inject_item_not_ordered,
    DiscrepancyType.WRONG_VAT_RATE: _inject_wrong_vat_rate,
    DiscrepancyType.PAYMENT_TERMS_DEVIATION: _inject_payment_terms_deviation,
    DiscrepancyType.BANK_DETAILS_CHANGED: _inject_bank_details_changed,
}


def _invoice_number(supplier: Party, number: int) -> str:
    """Invoice number styles differ between suppliers, as they do in practice."""
    style = int(supplier.party_id[-1]) % 3
    if style == 0:
        return f"RE-2026-{number:05d}"
    if style == 1:
        return f"RG{number:07d}"
    return f"2026/{number:05d}"


def generate_set(
    rng: random.Random,
    world: World,
    index: int,
    p_discrepant: float = 0.45,
    forced: list[DiscrepancyType] | None = None,
) -> GeneratedSet:
    """Generate one document set. ``forced`` injects exactly these types (used by tests)."""
    supplier = rng.choice(world.suppliers)
    order_date = ORDER_PERIOD_START + timedelta(days=rng.randint(0, ORDER_PERIOD_DAYS))
    delivery_date = order_date + timedelta(days=rng.randint(2, 10))

    order, variations = _build_order(rng, world, supplier, 1000 + index, order_date)
    delivery, delivery_variations = _build_delivery(rng, order, 50000 + index, delivery_date)
    items, wording = _initial_invoice_items(rng, order, delivery)
    draft = DraftSet(
        set_id=f"SET-{index:04d}",
        supplier=supplier,
        purchase_order=order,
        delivery_note=delivery,
        invoice_items=items,
        invoice_terms=supplier.contract.payment_terms,
        invoice_iban=supplier.party.iban or "",
        variations=variations + delivery_variations + wording,
    )

    if forced is not None:
        candidates, target = list(forced), len(forced)
    elif rng.random() < p_discrepant:
        candidates = rng.sample(sorted(DiscrepancyType), k=len(DiscrepancyType))
        target = 1 if rng.random() < 0.7 else 2
        # The volume-discount error is only possible in some sets; favour it there so the
        # dataset has enough examples of it for evaluation.
        if "volume_discount_applies" in draft.variations and rng.random() < 0.4:
            candidates.remove(DiscrepancyType.VOLUME_DISCOUNT_MISSING)
            candidates.insert(0, DiscrepancyType.VOLUME_DISCOUNT_MISSING)
    else:
        candidates, target = [], 0

    applied = 0
    totals_error = False
    for discrepancy_type in candidates:
        if applied >= target:
            break
        if discrepancy_type is DiscrepancyType.TOTALS_INCONSISTENT:
            # Applied last, so the stated totals deviate from the final line items.
            totals_error = True
            applied += 1
        elif INJECTORS[discrepancy_type](draft, rng):
            applied += 1

    invoice = _finalise_invoice(rng, draft, index, totals_error)
    return GeneratedSet(
        set_id=draft.set_id,
        supplier=supplier,
        purchase_order=order,
        delivery_note=delivery,
        invoice=invoice,
        discrepancies=draft.discrepancies,
        variations=sorted(set(draft.variations)),
    )


def _finalise_invoice(
    rng: random.Random, draft: DraftSet, index: int, totals_error: bool
) -> Invoice:
    order = draft.purchase_order
    issue_date = draft.delivery_note.delivery_date + timedelta(days=rng.randint(0, 5))
    seller = draft.supplier.party.model_copy(update={"iban": draft.invoice_iban})
    invoice = Invoice(
        invoice_number=_invoice_number(draft.supplier.party, 30000 + index),
        issue_date=issue_date,
        due_date=issue_date + timedelta(days=draft.invoice_terms.net_days),
        seller=seller,
        buyer=order.buyer,
        po_number=order.po_number,
        delivery_note_number=draft.delivery_note.delivery_note_number,
        contract_number=order.contract_number,
        items=draft.invoice_items,
        payment_terms=draft.invoice_terms,
        stated_totals=InvoiceTotals(net=Decimal(0), vat=Decimal(0), gross=Decimal(0)),
    )
    computed = invoice.computed_totals()
    stated = computed
    if totals_error:
        delta = Decimal(rng.choice(["0.01", "0.10", "1.00", "9.00", "-0.01", "-1.00"]))
        stated = InvoiceTotals(net=computed.net, vat=computed.vat, gross=computed.gross + delta)
        draft.discrepancies.append(
            Discrepancy(
                type=DiscrepancyType.TOTALS_INCONSISTENT,
                expected=str(computed.gross),
                actual=str(stated.gross),
                note="Bruttobetrag entspricht nicht Netto + USt.",
            )
        )
    return invoice.model_copy(update={"stated_totals": stated})
