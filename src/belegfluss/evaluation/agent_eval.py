"""Evaluate the matching agent against the ground truth.

Per discrepancy type it reports whether the agent found the finding with the right category
(this separates "price above contract" from "volume discount missing", which the rules alone
cannot) and whether it cited the labelled clause. Unverified proposals and model usage are
reported too, so the LLM adjudicator can be compared with the deterministic baseline on
exactly the same sets.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from belegfluss.agent.adjudicator import PRICE_TYPES
from belegfluss.agent.graph import match
from belegfluss.agent.models import ReviewFinding
from belegfluss.domain.discrepancies import Discrepancy
from belegfluss.domain.documents import DocumentKind
from belegfluss.domain.models import DeliveryNote, Invoice
from belegfluss.evaluation.extraction_eval import load_cached_document
from belegfluss.synth.ground_truth import GroundTruthSet


@dataclass
class AgentReport:
    sets: int = 0
    skipped: int = 0
    labels: Counter[str] = field(default_factory=Counter)
    category_ok: Counter[str] = field(default_factory=Counter)
    clause_ok: Counter[str] = field(default_factory=Counter)
    missed: Counter[str] = field(default_factory=Counter)
    extra: Counter[str] = field(default_factory=Counter)
    unverified: Counter[str] = field(default_factory=Counter)
    decisions: Counter[tuple[str, str]] = field(default_factory=Counter)
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    notes: list[str] = field(default_factory=list)


def _family(type_value: str) -> str:
    return "price" if type_value in {t.value for t in PRICE_TYPES} else type_value


def _pair(label: Discrepancy, findings: list[ReviewFinding]) -> ReviewFinding | None:
    return next(
        (
            f
            for f in findings
            if f.position == label.position and _family(f.type.value) == _family(label.type.value)
        ),
        None,
    )


def run_agent_eval(
    dataset: Path,
    graph: Any,
    source: Literal["ground-truth", "extracted"] = "ground-truth",
    cache_dir: Path | None = None,
    limit: int | None = None,
) -> AgentReport:
    report = AgentReport()
    paths = sorted((dataset / "ground_truth" / "sets").glob("*.json"))
    truths = [GroundTruthSet.model_validate_json(p.read_text(encoding="utf-8")) for p in paths]
    known_orders = {t.purchase_order.po_number for t in truths}
    for truth in truths:
        if limit is not None and report.sets >= limit:
            break
        invoice, note = truth.invoice, truth.delivery_note
        if source == "extracted":
            if cache_dir is None:
                raise ValueError("source='extracted' needs the extraction cache directory")
            cached_i = load_cached_document(cache_dir, dataset, truth, DocumentKind.INVOICE)
            cached_n = load_cached_document(cache_dir, dataset, truth, DocumentKind.DELIVERY_NOTE)
            if not (
                cached_i and cached_i.get("document") and cached_n and cached_n.get("document")
            ):
                report.skipped += 1
                continue
            invoice = Invoice.model_validate(cached_i["document"])
            note = DeliveryNote.model_validate(cached_n["document"])
        report.sets += 1
        start = time.perf_counter()
        result = match(graph, invoice, truth.purchase_order, note, known_orders)
        report.seconds += time.perf_counter() - start
        report.input_tokens += result.llm_input_tokens
        report.output_tokens += result.llm_output_tokens
        report.decisions[(truth.decision.value, result.decision.value)] += 1

        paired: set[str] = set()
        for label in truth.discrepancies:
            kind = label.type.value
            report.labels[kind] += 1
            finding = _pair(label, result.findings)
            if finding is None:
                report.missed[kind] += 1
                continue
            paired.add(finding.finding_id)
            if finding.type is label.type:
                report.category_ok[kind] += 1
                if finding.clause_id == label.clause_id:
                    report.clause_ok[kind] += 1
                elif len(report.notes) < 15:
                    report.notes.append(
                        f"{truth.set_id} {kind}: cited {finding.clause_id!r}, "
                        f"label {label.clause_id!r}"
                    )
            elif len(report.notes) < 15:
                report.notes.append(f"{truth.set_id}: {kind} classified as {finding.type.value}")
        for finding in result.findings:
            if not finding.verified:
                report.unverified[finding.type.value] += 1
            if finding.finding_id not in paired:
                report.extra[finding.type.value] += 1
    return report


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f} %" if whole else "–"


def to_markdown(report: AgentReport) -> str:
    types = sorted(set(report.labels) | set(report.extra))
    lines = [
        f"Sets evaluated: {report.sets} (skipped without extraction: {report.skipped})\n",
        "| discrepancy | labels | category correct | category + clause correct | missed "
        "| extra findings | unverified |",
        "|---|---|---|---|---|---|---|",
    ]
    for t in types:
        n = report.labels[t]
        lines.append(
            f"| {t} | {n} | {_pct(report.category_ok[t], n)} | {_pct(report.clause_ok[t], n)} "
            f"| {report.missed[t]} | {report.extra[t]} | {report.unverified[t]} |"
        )
    d = report.decisions
    avg = report.seconds / report.sets if report.sets else 0.0
    lines += [
        "",
        "| truth \\ decision | approve | review |",
        "|---|---|---|",
        f"| approve | {d[('approve', 'approve')]} | {d[('approve', 'review')]} |",
        f"| review | {d[('review', 'approve')]} | {d[('review', 'review')]} |",
        "",
        f"Model tokens in / out: {report.input_tokens} / {report.output_tokens}; "
        f"average time per set: {avg:.2f} s",
    ]
    if report.notes:
        lines += ["", "Differences (first 15):", ""] + [f"- {n}" for n in report.notes]
    return "\n".join(lines)
