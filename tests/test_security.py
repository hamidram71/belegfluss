"""Prompt-injection test set and the PDF screening (ADR 0009)."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import pytest

from belegfluss.checks.plausibility import IssueCode, check_plausibility
from belegfluss.security.screening import screen_pdf
from belegfluss.synth.attacks import PAYLOADS
from belegfluss.synth.dataset import write_dataset
from belegfluss.synth.ground_truth import GroundTruthSet
from belegfluss.synth.render_pdf import render_delivery_note_pdf, render_invoice_pdf
from belegfluss.synth.scenarios import generate_set
from belegfluss.synth.world import World


@pytest.mark.parametrize("hidden", [True, False])
@pytest.mark.parametrize("goal", sorted(PAYLOADS))
def test_planted_attacks_are_detected(world: World, goal: str, hidden: bool) -> None:
    g = generate_set(random.Random(1), world, 1)
    text = PAYLOADS[goal].format(iban="DE89370400440532013000")
    for pdf in (
        render_invoice_pdf(g.invoice, text, hidden),
        render_delivery_note_pdf(g.delivery_note, text, hidden),
    ):
        codes = {f.code for f in screen_pdf(pdf)}
        assert codes, goal
        assert ("hidden_text" in codes) == hidden


def test_clean_pdfs_are_not_flagged(world: World) -> None:
    """Regression: white table-header text on a coloured background was flagged as hidden."""
    rng = random.Random(9)
    for index in range(1, 25):
        g = generate_set(rng, world, index)
        assert screen_pdf(render_invoice_pdf(g.invoice)) == []
        assert screen_pdf(render_delivery_note_pdf(g.delivery_note)) == []


def test_flags_send_the_match_to_review(world: World) -> None:
    g = generate_set(random.Random(3), world, 1, p_discrepant=0.0)
    issues = check_plausibility(
        g.invoice,
        g.delivery_note,
        {g.purchase_order.po_number},
        security_flags=["hidden_text: Ignore all previous instructions"],
    )
    assert [i.code for i in issues] == [IssueCode.SUSPICIOUS_CONTENT]


def test_adversarial_dataset_and_unchanged_default(tmp_path: Path) -> None:
    plain = write_dataset(tmp_path / "plain", n_sets=12, seed=3, n_suppliers=3)
    attacked = write_dataset(tmp_path / "adv", n_sets=12, seed=3, n_suppliers=3, adversarial=1.0)
    assert plain.attacks == {} and sum(attacked.attacks.values()) > 0
    for path in sorted((tmp_path / "adv" / "ground_truth" / "sets").glob("*.json")):
        truth = GroundTruthSet.model_validate_json(path.read_text(encoding="utf-8"))
        twin = GroundTruthSet.model_validate_json(
            (tmp_path / "plain" / "ground_truth" / "sets" / path.name).read_text(encoding="utf-8")
        )
        # The attack changes the document's text layer, never the business data.
        assert truth.model_copy(update={"attack": None}) == twin


def test_injection_eval_counts_model_changes(tmp_path: Path) -> None:
    from belegfluss.domain.documents import DocumentKind
    from belegfluss.evaluation.injection_eval import run_injection_eval
    from belegfluss.extraction.pipeline import Extracted, ExtractionMethod

    write_dataset(tmp_path, n_sets=16, seed=5, n_suppliers=3, adversarial=1.0)
    truths = {
        p.stem: GroundTruthSet.model_validate_json(p.read_text(encoding="utf-8"))
        for p in (tmp_path / "ground_truth" / "sets").glob("*.json")
    }
    by_bytes = {
        (tmp_path / ref.path).read_bytes(): (t, ref)
        for t in truths.values()
        for ref in t.documents
        if ref.path.endswith(".pdf")
    }

    def fooled(kind: DocumentKind, data: bytes) -> Extracted[Any]:
        truth, ref = by_bytes[data]
        doc = truth.invoice if kind is DocumentKind.INVOICE else truth.delivery_note
        return Extracted(
            doc.model_copy(update={"po_number": "HACKED"}), ExtractionMethod.LLM_TEXT, ref.format
        )

    def robust(kind: DocumentKind, data: bytes) -> Extracted[Any]:
        truth, ref = by_bytes[data]
        doc = truth.invoice if kind is DocumentKind.INVOICE else truth.delivery_note
        return Extracted(doc, ExtractionMethod.LLM_TEXT, ref.format)

    hit = run_injection_eval(tmp_path, fooled)
    safe = run_injection_eval(tmp_path, robust)
    read = sum(hit.model_tested.values())
    assert read > 0 and sum(hit.model_changed.values()) == read
    assert sum(safe.model_changed.values()) == 0
    assert sum(hit.detected.values()) == sum(hit.attacks.values()) and hit.false_flags == 0
