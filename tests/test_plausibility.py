"""The plausibility checks against the kinds of misreads seen in the first real LLM run
(scans: a wrong order number on a delivery note, a wrong invoice date, a wrong invoice number)."""

from __future__ import annotations

import random
from datetime import timedelta

from belegfluss.checks.plausibility import IssueCode, check_plausibility
from belegfluss.synth.scenarios import GeneratedSet, generate_set
from belegfluss.synth.world import World


def _sets(world: World, n: int = 60) -> list[GeneratedSet]:
    rng = random.Random(77)
    return [generate_set(rng, world, i) for i in range(1, n + 1)]


def _codes(generated: GeneratedSet, known: set[str], **changes: object) -> set[IssueCode]:
    invoice = generated.invoice.model_copy(update=changes.get("invoice", {}))  # type: ignore[arg-type]
    note = generated.delivery_note.model_copy(update=changes.get("note", {}))  # type: ignore[arg-type]
    return {i.code for i in check_plausibility(invoice, note, known)}


def test_correct_documents_are_never_flagged(world: World) -> None:
    sets = _sets(world)
    known = {g.purchase_order.po_number for g in sets}
    seen: set[tuple[str, str]] = set()
    for g in sets:
        assert check_plausibility(g.invoice, g.delivery_note, known, seen) == []


def test_misread_order_number_on_delivery_note_is_flagged(world: World) -> None:
    sets = _sets(world)
    known = {g.purchase_order.po_number for g in sets}
    g = sets[0]
    misread = g.delivery_note.po_number.replace("BE-2026-0", "BE-2026-8")
    codes = _codes(g, known, note={"po_number": misread})
    assert {IssueCode.UNKNOWN_ORDER, IssueCode.ORDER_MISMATCH} <= codes


def test_misread_invoice_date_is_flagged_when_due_date_was_read_correctly(world: World) -> None:
    g = _sets(world)[1]
    known = {g.purchase_order.po_number}
    codes = _codes(g, known, invoice={"issue_date": g.invoice.issue_date + timedelta(days=1)})
    assert IssueCode.DUE_DATE_INCONSISTENT in codes


def test_misread_invoice_number_is_not_detectable(world: World) -> None:
    """Documented limitation: a wrong invoice number is internally consistent."""
    g = _sets(world)[2]
    known = {g.purchase_order.po_number}
    assert _codes(g, known, invoice={"invoice_number": g.invoice.invoice_number + "1"}) == set()


def test_duplicate_invoice_is_flagged(world: World) -> None:
    g = _sets(world)[3]
    known, seen = {g.purchase_order.po_number}, set[tuple[str, str]]()
    assert check_plausibility(g.invoice, g.delivery_note, known, seen) == []
    second = check_plausibility(g.invoice, g.delivery_note, known, seen)
    assert [i.code for i in second] == [IssueCode.DUPLICATE_INVOICE]


def test_extraction_warnings_become_issues(world: World) -> None:
    g = _sets(world)[4]
    issues = check_plausibility(
        g.invoice, g.delivery_note, {g.purchase_order.po_number}, warnings=["line 2: unit missing"]
    )
    assert [i.code for i in issues] == [IssueCode.EXTRACTION_WARNING]
