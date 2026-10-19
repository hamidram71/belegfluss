from __future__ import annotations

from pathlib import Path

import pytest

from belegfluss.synth.dataset import write_dataset
from belegfluss.synth.ground_truth import Manifest
from belegfluss.synth.world import World, build_world


@pytest.fixture(scope="session")
def world() -> World:
    return build_world(seed=7)


@pytest.fixture(scope="session")
def small_dataset(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Manifest]:
    root = tmp_path_factory.mktemp("dataset")
    manifest = write_dataset(root, n_sets=8, seed=11, n_suppliers=4)
    return root, manifest
