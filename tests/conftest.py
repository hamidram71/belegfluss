from __future__ import annotations

import os
from pathlib import Path

import pytest

from belegfluss.config import Settings, get_settings
from belegfluss.master_data import MasterData
from belegfluss.synth.dataset import write_dataset
from belegfluss.synth.ground_truth import Manifest
from belegfluss.synth.world import World, build_world, master_data_from_world


@pytest.fixture(autouse=True)
def isolated_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never read the developer's .env or environment.

    Regression: a local .env with BELEGFLUSS_DATABASE_URL made API tests connect to a database
    that was not running (and an embedding model in .env could have called the real API).
    Tests that need a setting pass it explicitly; tests of .env handling pass ``_env_file``.
    """
    for name in list(os.environ):
        if name.startswith("BELEGFLUSS_") and name != "BELEGFLUSS_TEST_PG_DSN":
            monkeypatch.delenv(name)
    for name in ("OPENAI_API_KEY", "AZURE_OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def world() -> World:
    return build_world(seed=7)


@pytest.fixture(scope="session")
def small_dataset(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Manifest]:
    root = tmp_path_factory.mktemp("dataset")
    manifest = write_dataset(root, n_sets=8, seed=11, n_suppliers=4)
    return root, manifest


@pytest.fixture(scope="session")
def master(world: World) -> MasterData:
    return master_data_from_world(world)
