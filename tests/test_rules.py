"""With perfect documents, the rules must find every labeled discrepancy and nothing else."""

from __future__ import annotations

import random

from belegfluss.checks.rules import NEEDS_CONTRACT_REVIEW, decide, run_rules
from belegfluss.domain.discrepancies import Decision, DiscrepancyType
from belegfluss.master_data import MasterData
from belegfluss.synth.scenarios import generate_set
from belegfluss.synth.world import World

PRICE_TYPES = {DiscrepancyType.PRICE_ABOVE_CONTRACT, DiscrepancyType.VOLUME_DISCOUNT_MISSING}


def _key(kind: DiscrepancyType, position: int | None) -> tuple[str, int | None]:
    return ("price" if kind in PRICE_TYPES else kind.value, position)


def test_rules_are_exact_on_perfect_input(world: World, master: MasterData) -> None:
    rng = random.Random(41)
    for index in range(1, 401):
        generated = generate_set(rng, world, index)
        findings = run_rules(
            generated.invoice, generated.purchase_order, generated.delivery_note, master
        )
        assert {_key(f.type, f.position) for f in findings} == {
            _key(d.type, d.position) for d in generated.discrepancies
        }, generated.set_id
        assert decide(findings) is generated.decision


def test_price_findings_are_marked_for_contract_review(world: World, master: MasterData) -> None:
    rng = random.Random(42)
    for index in range(1, 400):
        generated = generate_set(rng, world, index, forced=[DiscrepancyType.PRICE_ABOVE_CONTRACT])
        if generated.discrepancies:
            break
    findings = run_rules(
        generated.invoice, generated.purchase_order, generated.delivery_note, master
    )
    price = [f for f in findings if f.type is DiscrepancyType.PRICE_ABOVE_CONTRACT]
    assert price and price[0].note == NEEDS_CONTRACT_REVIEW


def test_unknown_supplier_is_never_approved(world: World, master: MasterData) -> None:
    generated = generate_set(random.Random(43), world, 1, p_discrepant=0.0)
    stranger = generated.invoice.seller.model_copy(
        update={"party_id": "UNRESOLVED", "vat_id": "DE999999999", "name": "Unbekannt GmbH"}
    )
    invoice = generated.invoice.model_copy(update={"seller": stranger})
    findings = run_rules(invoice, generated.purchase_order, generated.delivery_note, master)
    assert decide(findings) is Decision.REVIEW
