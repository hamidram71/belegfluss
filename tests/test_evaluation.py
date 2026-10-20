from __future__ import annotations

import hashlib
import json
from pathlib import Path

from belegfluss.domain.documents import DocumentKind
from belegfluss.evaluation import checks_eval, extraction_eval
from belegfluss.evaluation.cli import main
from belegfluss.extraction.pipeline import extract_invoice
from belegfluss.master_data import MasterData
from belegfluss.synth.ground_truth import Manifest


def test_extraction_eval_on_e_invoices_is_perfect(
    small_dataset: tuple[Path, Manifest], tmp_path: Path
) -> None:
    root, _ = small_dataset
    master = MasterData.load(root / "master_data")
    results = extraction_eval.run_extraction_eval(
        root,
        (DocumentKind.INVOICE,),
        lambda kind, data: extract_invoice(data, master, None),
        formats={"xrechnung_cii", "zugferd_pdf"},
        cache_dir=tmp_path,
    )
    stats = [s for by_format in results.values() for s in by_format.values()]
    assert stats and all(s.failed == 0 and s.exact == s.documents for s in stats)
    assert "fully correct documents" in extraction_eval.to_markdown(results)
    assert list(tmp_path.glob("*.invoice.json"))


def test_failures_are_reported_not_raised(small_dataset: tuple[Path, Manifest]) -> None:
    root, _ = small_dataset

    def broken(kind: DocumentKind, data: bytes) -> object:
        raise RuntimeError("boom")

    results = extraction_eval.run_extraction_eval(root, (DocumentKind.INVOICE,), broken)  # type: ignore[arg-type]
    stats = [s for by_format in results.values() for s in by_format.values()]
    assert sum(s.failed for s in stats) == 8
    assert "boom" in extraction_eval.to_markdown(results)


def test_checks_eval_on_ground_truth_is_perfect(small_dataset: tuple[Path, Manifest]) -> None:
    root, manifest = small_dataset
    report = checks_eval.run_checks_eval(root, "ground-truth")
    assert report.sets == 8
    assert sum(report.fp.values()) == 0 and sum(report.fn.values()) == 0
    assert report.decisions[("review", "review")] == manifest.decisions.get("review", 0)


def test_cli_runs_without_llm(
    small_dataset: tuple[Path, Manifest], tmp_path: Path, monkeypatch: object
) -> None:
    root, _ = small_dataset
    import pytest

    mp = pytest.MonkeyPatch()
    mp.chdir(tmp_path)
    try:
        assert main(["extraction", "--data", str(root), "--no-llm", "--kinds", "invoice"]) == 0
        assert main(["checks", "--data", str(root)]) == 0
        assert len(list((tmp_path / "reports").glob("*.md"))) == 2
    finally:
        mp.undo()


def test_cache_is_ignored_when_the_document_changed(tmp_path: Path) -> None:
    from belegfluss.evaluation.extraction_eval import _cache_path, load_cached

    cache = tmp_path / "cache"
    cache.mkdir()
    entry = {"sha256": hashlib.sha256(b"original").hexdigest(), "document": {"x": 1}}
    _cache_path(cache, "SET-0001", DocumentKind.INVOICE).write_text(json.dumps(entry))
    assert load_cached(cache, "SET-0001", DocumentKind.INVOICE, b"original") == entry
    assert load_cached(cache, "SET-0001", DocumentKind.INVOICE, b"regenerated") is None
    # Entries written before hashes were stored are treated as stale.
    _cache_path(cache, "SET-0002", DocumentKind.INVOICE).write_text(json.dumps({"document": {}}))
    assert load_cached(cache, "SET-0002", DocumentKind.INVOICE, b"original") is None
