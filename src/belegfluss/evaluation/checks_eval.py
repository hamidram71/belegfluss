"""Precision and recall of the rule-based checks, end to end.

``source="ground-truth"`` feeds the checks perfect documents and measures the rules alone.
``source="extracted"`` uses cached extraction results and measures the full pipeline.
Volume-discount findings count as matched by a price finding at the same position, because
telling them apart needs the contract (delivery 3); the report says so.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from belegfluss.checks.plausibility import check_plausibility
from belegfluss.checks.rules import decide, run_rules
from belegfluss.domain.discrepancies import Decision, Discrepancy, DiscrepancyType
from belegfluss.domain.documents import DocumentKind
from belegfluss.domain.models import DeliveryNote, Invoice
from belegfluss.evaluation.extraction_eval import load_cached_document
from belegfluss.master_data import MasterData
from belegfluss.synth.ground_truth import GroundTruthSet

PRICE = "price_deviation"


def _key(d: Discrepancy) -> tuple[str, int | None]:
    price_types = (DiscrepancyType.PRICE_ABOVE_CONTRACT, DiscrepancyType.VOLUME_DISCOUNT_MISSING)
    return (PRICE if d.type in price_types else d.type.value, d.position)


@dataclass
class ChecksReport:
    sets: int = 0
    skipped: int = 0
    tp: Counter[str] = field(default_factory=Counter)
    fp: Counter[str] = field(default_factory=Counter)
    fn: Counter[str] = field(default_factory=Counter)
    decisions: Counter[tuple[str, str]] = field(default_factory=Counter)
    false_alarm_variations: Counter[str] = field(default_factory=Counter)
    # (extraction correct?, plausibility flagged?) -> number of sets
    plausibility: Counter[tuple[bool, bool]] = field(default_factory=Counter)
    plausibility_codes: Counter[str] = field(default_factory=Counter)


def run_checks_eval(
    dataset: Path,
    source: Literal["ground-truth", "extracted"] = "ground-truth",
    cache_dir: Path | None = None,
    limit: int | None = None,
) -> ChecksReport:
    master = MasterData.load(dataset / "master_data")
    report = ChecksReport()
    truth_paths = sorted((dataset / "ground_truth" / "sets").glob("*.json"))
    # The ERP knows every order; a misread order number on a document is not among them.
    known_orders = {
        GroundTruthSet.model_validate_json(p.read_text(encoding="utf-8")).purchase_order.po_number
        for p in truth_paths
    }
    seen_invoices: set[tuple[str, str]] = set()
    for path in truth_paths:
        if limit is not None and report.sets + report.skipped >= limit:
            break
        truth = GroundTruthSet.model_validate_json(path.read_text(encoding="utf-8"))
        invoice, note = truth.invoice, truth.delivery_note
        if source == "extracted":
            if cache_dir is None:
                raise ValueError("source='extracted' needs the extraction cache directory")
            cached_invoice = load_cached_document(cache_dir, dataset, truth, DocumentKind.INVOICE)
            cached_note = load_cached_document(
                cache_dir, dataset, truth, DocumentKind.DELIVERY_NOTE
            )
            if not (
                cached_invoice
                and cached_invoice.get("document")
                and cached_note
                and cached_note.get("document")
            ):
                report.skipped += 1
                continue
            invoice = Invoice.model_validate(cached_invoice["document"])
            note = DeliveryNote.model_validate(cached_note["document"])
        report.sets += 1
        issues = check_plausibility(invoice, note, known_orders, seen_invoices)
        extraction_correct = invoice == truth.invoice and note == truth.delivery_note
        report.plausibility[(extraction_correct, bool(issues))] += 1
        report.plausibility_codes.update(i.code.value for i in issues)
        findings = run_rules(invoice, truth.purchase_order, note, master)
        got, want = {_key(f) for f in findings}, {_key(d) for d in truth.discrepancies}
        report.tp.update(k for k, _ in got & want)
        report.fp.update(k for k, _ in got - want)
        report.fn.update(k for k, _ in want - got)
        decision = decide(findings)
        report.decisions[(truth.decision.value, decision.value)] += 1
        if truth.decision is Decision.APPROVE and decision is Decision.REVIEW:
            report.false_alarm_variations.update(truth.variations or ["none"])
    return report


def to_markdown(report: ChecksReport) -> str:
    types = sorted(set(report.tp) | set(report.fp) | set(report.fn))
    lines = [
        f"Sets evaluated: {report.sets} (skipped without extraction: {report.skipped})\n",
        "| finding | TP | FP | FN | precision | recall |",
        "|---|---|---|---|---|---|",
    ]
    for t in types:
        tp, fp, fn = report.tp[t], report.fp[t], report.fn[t]
        precision = f"{100 * tp / (tp + fp):.1f} %" if tp + fp else "–"
        recall = f"{100 * tp / (tp + fn):.1f} %" if tp + fn else "–"
        lines.append(f"| {t} | {tp} | {fp} | {fn} | {precision} | {recall} |")
    d = report.decisions
    lines += [
        "",
        "| truth \\ decision | approve | review |",
        "|---|---|---|",
        f"| approve | {d[('approve', 'approve')]} | {d[('approve', 'review')]} |",
        f"| review | {d[('review', 'approve')]} | {d[('review', 'review')]} |",
        "",
        f"`{PRICE}` combines price_above_contract and volume_discount_missing: telling them "
        "apart needs the contract text (agent with RAG, delivery 3).",
    ]
    p = report.plausibility
    lines += [
        "",
        "Plausibility checks (signs of extraction errors):",
        "",
        "| extraction \\ flagged | flagged | not flagged |",
        "|---|---|---|",
        f"| correct | {p[(True, True)]} | {p[(True, False)]} |",
        f"| not fully correct | {p[(False, True)]} | {p[(False, False)]} |",
    ]
    if report.plausibility_codes:
        lines.append(
            "\nFlags by code: "
            + ", ".join(f"{k}: {v}" for k, v in sorted(report.plausibility_codes.items()))
        )
    if report.false_alarm_variations:
        lines.append(
            "\nFalse alarms on clean sets by legitimate variation: "
            + ", ".join(f"{k}: {v}" for k, v in report.false_alarm_variations.items())
        )
    return "\n".join(lines)
