"""The generator must produce exactly what the ground truth claims."""

from __future__ import annotations

import random
from decimal import Decimal

import pytest

from belegfluss.domain.discrepancies import Decision, DiscrepancyType
from belegfluss.domain.identifiers import is_valid_iban
from belegfluss.synth.catalog import by_sku
from belegfluss.synth.scenarios import GeneratedSet, generate_set
from belegfluss.synth.world import World


def _find(world: World, kind: DiscrepancyType) -> GeneratedSet:
    """Some types only apply to some sets (e.g. a volume discount); search until one fits."""
    rng = random.Random(99)
    for index in range(1, 400):
        generated = generate_set(rng, world, index, forced=[kind])
        if any(d.type is kind for d in generated.discrepancies):
            return generated
    raise AssertionError(f"could not generate {kind}")


def test_generation_is_deterministic(world: World) -> None:
    first = [generate_set(random.Random(5), world, i) for i in range(1, 20)]
    second = [generate_set(random.Random(5), world, i) for i in range(1, 20)]
    assert [g.invoice.model_dump() for g in first] == [g.invoice.model_dump() for g in second]


def test_clean_sets_are_internally_consistent(world: World) -> None:
    rng = random.Random(3)
    for index in range(1, 120):
        generated = generate_set(rng, world, index, p_discrepant=0.0)
        invoice, order = generated.invoice, generated.purchase_order
        delivered = {d.sku: d.quantity for d in generated.delivery_note.items}
        ordered = {o.sku: o for o in order.items}
        assert generated.decision is Decision.APPROVE
        assert invoice.stated_totals == invoice.computed_totals()
        assert invoice.seller.iban == generated.supplier.party.iban
        assert invoice.payment_terms == generated.supplier.contract.payment_terms
        for item in invoice.items:
            assert item.quantity == delivered[item.sku]
            assert item.unit_price == ordered[item.sku].unit_price
            assert item.vat_rate == by_sku(item.sku).vat_rate


def test_discrepant_share_is_roughly_as_configured(world: World) -> None:
    rng = random.Random(8)
    sets = [generate_set(rng, world, i, p_discrepant=0.45) for i in range(1, 301)]
    share = sum(g.decision is Decision.REVIEW for g in sets) / len(sets)
    assert 0.35 < share < 0.55


@pytest.mark.parametrize("kind", list(DiscrepancyType))
def test_each_discrepancy_type_is_really_in_the_invoice(
    world: World, kind: DiscrepancyType
) -> None:
    generated = _find(world, kind)
    label = next(d for d in generated.discrepancies if d.type is kind)
    invoice = generated.invoice
    contract = generated.supplier.contract
    item = next((i for i in invoice.items if i.position == label.position), None)
    ordered = {o.sku: o for o in generated.purchase_order.items}
    delivered = {d.sku: d.quantity for d in generated.delivery_note.items}

    if kind is DiscrepancyType.PRICE_ABOVE_CONTRACT:
        assert item is not None
        expected = contract.agreed_unit_price(item.sku, ordered[item.sku].quantity)
        assert expected is not None and item.unit_price > expected
        assert label.clause_id == contract.price_list_clause_id
    elif kind is DiscrepancyType.VOLUME_DISCOUNT_MISSING:
        assert item is not None and contract.volume_discount is not None
        assert ordered[item.sku].quantity >= contract.volume_discount.min_quantity
        assert item.unit_price == Decimal(label.actual or "")
        assert item.unit_price > Decimal(label.expected or "")
    elif kind is DiscrepancyType.QUANTITY_EXCEEDS_DELIVERY:
        assert item is not None and item.quantity > delivered[item.sku]
    elif kind is DiscrepancyType.ITEM_NOT_ORDERED:
        assert item is not None and item.sku not in ordered
    elif kind is DiscrepancyType.WRONG_VAT_RATE:
        assert item is not None and item.vat_rate != by_sku(item.sku).vat_rate
    elif kind is DiscrepancyType.TOTALS_INCONSISTENT:
        assert invoice.stated_totals != invoice.computed_totals()
    elif kind is DiscrepancyType.PAYMENT_TERMS_DEVIATION:
        assert invoice.payment_terms != contract.payment_terms
        assert label.clause_id == contract.payment_terms_clause_id
    elif kind is DiscrepancyType.BANK_DETAILS_CHANGED:
        assert invoice.seller.iban != generated.supplier.party.iban
        assert invoice.seller.iban is not None and is_valid_iban(invoice.seller.iban)
    assert generated.decision is Decision.REVIEW


def test_contract_clauses_reference_existing_ids(world: World) -> None:
    for supplier in world.suppliers:
        contract = supplier.contract
        ids = {c.clause_id for c in contract.clauses}
        for ref in (
            contract.price_list_clause_id,
            contract.payment_terms_clause_id,
            contract.partial_delivery_clause_id,
            contract.bank_details_clause_id,
        ):
            assert ref in ids
        if contract.volume_discount:
            assert contract.volume_discount.clause_id in ids
