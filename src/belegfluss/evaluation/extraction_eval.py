"""Field-level accuracy of document extraction, reported per input format.

Results are cached per document, so a second run (or the checks evaluation) does not pay for
the same LLM calls again.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from belegfluss.domain.documents import DocumentKind
from belegfluss.domain.models import DeliveryNote, Invoice
from belegfluss.extraction.llm import LLMUsage
from belegfluss.extraction.pipeline import Extracted
from belegfluss.synth.ground_truth import GroundTruthSet

INVOICE_FIELDS: dict[str, Callable[[Invoice], object]] = {
    "invoice_number": lambda i: i.invoice_number,
    "issue_date": lambda i: i.issue_date,
    "due_date": lambda i: i.due_date,
    "po_number": lambda i: i.po_number,
    "delivery_note_number": lambda i: i.delivery_note_number,
    "seller_identified": lambda i: i.seller.party_id,
    "seller_iban": lambda i: i.seller.iban,
    "payment_terms": lambda i: i.payment_terms,
    "total_net": lambda i: i.stated_totals.net,
    "total_vat": lambda i: i.stated_totals.vat,
    "total_gross": lambda i: i.stated_totals.gross,
}
INVOICE_LINE_FIELDS = ("quantity", "unit", "unit_price", "vat_rate")
NOTE_FIELDS: dict[str, Callable[[DeliveryNote], object]] = {
    "delivery_note_number": lambda n: n.delivery_note_number,
    "delivery_date": lambda n: n.delivery_date,
    "po_number": lambda n: n.po_number,
    "supplier_identified": lambda n: n.supplier.party_id,
}
NOTE_LINE_FIELDS = ("quantity", "unit")


@dataclass
class FormatStats:
    documents: int = 0
    failed: int = 0
    exact: int = 0
    field_hits: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    field_total: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    lines_expected: int = 0
    lines_found: int = 0
    lines_matched: int = 0
    usage: LLMUsage = field(default_factory=LLMUsage)
    errors: list[str] = field(default_factory=list)
    mismatches: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            out.update(_flatten(item, f"{prefix}.{key}" if prefix else str(key)))
        return out
    if isinstance(value, list):
        out = {f"{prefix}.len": len(value)}
        for index, item in enumerate(value):
            out.update(_flatten(item, f"{prefix}[{index}]"))
        return out
    return {prefix: value}


def differing_fields(expected: Any, actual: Any) -> list[str]:
    """Paths of all fields that differ, e.g. ``items[2].description``, for the report."""
    a = _flatten(expected.model_dump(mode="json"))
    b = _flatten(actual.model_dump(mode="json"))
    return sorted(k for k in a.keys() | b.keys() if a.get(k) != b.get(k))


def _compare_lines(
    stats: FormatStats, expected: list[Any], actual: list[Any], fields: tuple[str, ...]
) -> None:
    stats.lines_expected += len(expected)
    stats.lines_found += len(actual)
    by_sku = {line.sku: line for line in actual}
    for line in expected:
        got = by_sku.get(line.sku)
        if got is None:
            continue
        stats.lines_matched += 1
        for name in fields:
            stats.field_total[f"line.{name}"] += 1
            stats.field_hits[f"line.{name}"] += getattr(got, name) == getattr(line, name)


def score(
    stats: FormatStats,
    expected: Invoice | DeliveryNote,
    actual: Invoice | DeliveryNote,
    label: str = "",
) -> None:
    stats.documents += 1
    stats.exact += expected == actual
    if expected != actual:
        fields = differing_fields(expected, actual)
        shown = ", ".join(fields[:6]) + (f" (+{len(fields) - 6} more)" if len(fields) > 6 else "")
        stats.mismatches.append(f"{label}: {shown}")
    if isinstance(expected, Invoice) and isinstance(actual, Invoice):
        for name, get_invoice_field in INVOICE_FIELDS.items():
            stats.field_total[name] += 1
            stats.field_hits[name] += get_invoice_field(actual) == get_invoice_field(expected)
        _compare_lines(stats, expected.items, actual.items, INVOICE_LINE_FIELDS)
    elif isinstance(expected, DeliveryNote) and isinstance(actual, DeliveryNote):
        for name, get_note_field in NOTE_FIELDS.items():
            stats.field_total[name] += 1
            stats.field_hits[name] += get_note_field(actual) == get_note_field(expected)
        _compare_lines(stats, expected.items, actual.items, NOTE_LINE_FIELDS)


def _cache_path(cache_dir: Path, set_id: str, kind: DocumentKind) -> Path:
    return cache_dir / f"{set_id}.{kind.value}.json"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_cached(
    cache_dir: Path, set_id: str, kind: DocumentKind, data: bytes
) -> dict[str, Any] | None:
    """Return a cached extraction only if it was made from exactly these document bytes.

    The key alone (set id + kind) is not enough: a regenerated dataset reuses set ids, and a
    stale result would silently be scored against new ground truth.
    """
    path = _cache_path(cache_dir, set_id, kind)
    if not path.exists():
        return None
    entry: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return entry if entry.get("sha256") == _sha256(data) else None


def save_cached(
    cache_dir: Path, set_id: str, kind: DocumentKind, data: bytes, result: Extracted[Any]
) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    _cache_path(cache_dir, set_id, kind).write_text(
        json.dumps(
            {
                "sha256": _sha256(data),
                "method": result.method.value,
                "document": result.document.model_dump(mode="json"),
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )


def load_cached_document(
    cache_dir: Path, dataset: Path, truth: GroundTruthSet, kind: DocumentKind
) -> dict[str, Any] | None:
    ref = next((r for r in truth.documents if r.kind is kind), None)
    if ref is None:
        return None
    return load_cached(cache_dir, truth.set_id, kind, (dataset / ref.path).read_bytes())


def run_extraction_eval(
    dataset: Path,
    kinds: tuple[DocumentKind, ...],
    extract: Callable[[DocumentKind, bytes], Extracted[Any]],
    limit: int | None = None,
    formats: set[str] | None = None,
    cache_dir: Path | None = None,
) -> dict[str, dict[str, FormatStats]]:
    """Return stats[kind][input_format]."""
    results: dict[str, dict[str, FormatStats]] = defaultdict(lambda: defaultdict(FormatStats))
    truths = sorted((dataset / "ground_truth" / "sets").glob("*.json"))
    evaluated = 0
    for path in truths:
        truth = GroundTruthSet.model_validate_json(path.read_text(encoding="utf-8"))
        selected = [
            r
            for r in truth.documents
            if r.kind in kinds and (formats is None or r.format.value in formats)
        ]
        if not selected:
            continue
        if limit is not None and evaluated >= limit:
            break
        evaluated += 1
        for ref in selected:
            stats = results[ref.kind.value][ref.format.value]
            expected: Invoice | DeliveryNote = (
                truth.invoice if ref.kind is DocumentKind.INVOICE else truth.delivery_note
            )
            data = (dataset / ref.path).read_bytes()
            cached = load_cached(cache_dir, truth.set_id, ref.kind, data) if cache_dir else None
            if cached is not None and cached.get("document") is not None:
                model = Invoice if ref.kind is DocumentKind.INVOICE else DeliveryNote
                score(stats, expected, model.model_validate(cached["document"]), truth.set_id)
                continue
            try:
                result = extract(ref.kind, data)
            except Exception as exc:  # report, do not abort the whole run
                stats.documents += 1
                stats.failed += 1
                stats.errors.append(f"{truth.set_id}: {type(exc).__name__}: {exc}"[:300])
                continue
            stats.usage.add(result.usage)
            stats.warnings += [f"{truth.set_id}: {w}" for w in result.warnings]
            score(stats, expected, result.document, truth.set_id)
            if cache_dir:
                save_cached(cache_dir, truth.set_id, ref.kind, data, result)
    return results


def _field_rate(name: str) -> Callable[[FormatStats], str]:
    return lambda s: _pct(s.field_hits[name], s.field_total[name])


def _pct(hits: int, total: int) -> str:
    return f"{100 * hits / total:.1f} %" if total else "–"


def to_markdown(results: dict[str, dict[str, FormatStats]]) -> str:
    out: list[str] = []
    for kind, by_format in results.items():
        out.append(f"### {kind}\n")
        formats = sorted(by_format)
        out.append("| metric | " + " | ".join(formats) + " |")
        out.append("|---|" + "---|" * len(formats))
        rows: list[tuple[str, Callable[[FormatStats], str]]] = [
            ("documents", lambda s: str(s.documents)),
            ("failed", lambda s: str(s.failed)),
            ("fully correct documents", lambda s: _pct(s.exact, s.documents)),
            ("line recall (by SKU)", lambda s: _pct(s.lines_matched, s.lines_expected)),
        ]
        names = sorted({n for s in by_format.values() for n in s.field_total})
        rows += [(n, _field_rate(n)) for n in names]
        rows += [
            ("LLM calls", lambda s: str(s.usage.calls)),
            ("tokens in / out", lambda s: f"{s.usage.input_tokens} / {s.usage.output_tokens}"),
            (
                "avg latency per call",
                lambda s: f"{s.usage.seconds / s.usage.calls:.1f} s" if s.usage.calls else "–",
            ),
        ]
        for label, fn in rows:
            out.append(f"| {label} | " + " | ".join(fn(by_format[f]) for f in formats) + " |")
        out.append("")
        for title, attr in (
            ("Errors", "errors"),
            ("Documents not fully correct: differing fields", "mismatches"),
            ("Extraction warnings", "warnings"),
        ):
            entries = [f"{f}: {e}" for f in formats for e in getattr(by_format[f], attr)]
            if entries:
                out.append(f"{title} (first 15):\n")
                out += [f"- {e}" for e in entries[:15]]
                out.append("")
    return "\n".join(out)
