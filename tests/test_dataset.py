from __future__ import annotations

import json
from pathlib import Path

from belegfluss.synth.cli import main
from belegfluss.synth.ground_truth import GroundTruthSet, Manifest


def test_dataset_layout_and_manifest(small_dataset: tuple[Path, Manifest]) -> None:
    root, manifest = small_dataset
    assert manifest.n_sets == 8
    assert sum(manifest.decisions.values()) == 8
    assert len(list((root / "contracts").glob("*.pdf"))) == 4
    assert json.loads((root / "manifest.json").read_text(encoding="utf-8"))["seed"] == 11

    truths = sorted((root / "ground_truth" / "sets").glob("*.json"))
    assert len(truths) == 8
    for path in truths:
        truth = GroundTruthSet.model_validate_json(path.read_text(encoding="utf-8"))
        for ref in truth.documents:
            assert (root / ref.path).is_file()
            assert ref.path.startswith("sets/")


def test_ground_truth_never_inside_input_folders(small_dataset: tuple[Path, Manifest]) -> None:
    root, _ = small_dataset
    leaked = [p for p in (root / "sets").rglob("*") if "ground_truth" in p.name]
    assert not leaked
    for set_dir in (root / "sets").iterdir():
        names = {p.stem for p in set_dir.iterdir()}
        assert names == {"purchase_order", "delivery_note", "invoice"}


def test_cli_refuses_non_empty_directory(tmp_path: Path) -> None:
    (tmp_path / "existing.txt").write_text("keep me")
    assert main(["--out", str(tmp_path), "--sets", "1"]) == 1
    assert (tmp_path / "existing.txt").read_text(encoding="utf-8") == "keep me"
