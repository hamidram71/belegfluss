"""End to end through the API: upload, match, review queue, human decision."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from belegfluss.api.main import create_app
from belegfluss.api.routes.documents import get_llm
from belegfluss.config import Settings, get_settings
from belegfluss.domain.documents import DocumentFormat
from belegfluss.synth.ground_truth import GroundTruthSet, Manifest

from .fakes import FakeLLM, transcribe_delivery_note, transcribe_invoice

LLM_FORMATS = {DocumentFormat.PDF, DocumentFormat.SCAN}


class Harness:
    def __init__(self, root: Path, tmp: Path, erp_dir: Path | None = None) -> None:
        self.root = root
        self.llm: FakeLLM | None = None
        app = create_app()
        settings = Settings(
            storage_dir=tmp / "documents",
            matches_dir=tmp / "matches",
            master_data_dir=root / "master_data",
            contracts_dir=root / "contracts",
            erp_orders_dir=erp_dir or root / "sets",
            adjudicator="deterministic",
        )
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_llm] = lambda: self.llm
        self.client = TestClient(app)

    def truths(self) -> list[GroundTruthSet]:
        paths = sorted((self.root / "ground_truth" / "sets").glob("*.json"))
        return [GroundTruthSet.model_validate_json(p.read_text(encoding="utf-8")) for p in paths]

    def upload(self, truth: GroundTruthSet) -> dict[str, Any]:
        responses: list[Any] = []
        ids = {}
        for ref in truth.documents:
            if ref.kind.value == "purchase_order":
                continue
            data = (self.root / ref.path).read_bytes()
            response = self.client.post("/v1/documents", files={"file": (ref.path, data)})
            assert response.status_code == 201
            ids[ref.kind.value] = response.json()["document_id"]
            if ref.format in LLM_FORMATS:
                responses.append(
                    transcribe_invoice(truth.invoice)
                    if ref.kind.value == "invoice"
                    else transcribe_delivery_note(truth.delivery_note)
                )
        # Invoices are extracted before delivery notes.
        responses.sort(key=lambda r: type(r).__name__ != "ExtractedInvoice")
        self.llm = FakeLLM(responses)
        return {
            "invoice_document_id": ids["invoice"],
            "delivery_note_document_id": ids["delivery_note"],
        }


@pytest.fixture()
def harness(small_dataset: tuple[Path, Manifest], tmp_path: Path) -> Iterator[Harness]:
    yield Harness(small_dataset[0], tmp_path)


def test_every_set_gets_the_expected_decision(harness: Harness) -> None:
    for truth in harness.truths():
        response = harness.client.post("/v1/matches", json=harness.upload(truth))
        assert response.status_code == 201, response.text
        record = response.json()
        assert record["result"]["decision"] == truth.decision.value, truth.set_id
        expected_status = "open" if truth.decision.value == "review" else "auto_approved"
        assert record["status"] == expected_status


def test_review_queue_and_human_decision(harness: Harness) -> None:
    truth = next(t for t in harness.truths() if t.decision.value == "review")
    record = harness.client.post("/v1/matches", json=harness.upload(truth)).json()
    queue = harness.client.get("/v1/review-queue").json()
    assert record["match_id"] in [r["match_id"] for r in queue]

    decision = {"approve": False, "reviewer": "hamid", "comment": "Preis klären"}
    decided = harness.client.post(f"/v1/matches/{record['match_id']}/decision", json=decision)
    assert decided.status_code == 200
    assert decided.json()["status"] == "rejected" and decided.json()["reviewer"] == "hamid"
    assert record["match_id"] not in [
        r["match_id"] for r in harness.client.get("/v1/review-queue").json()
    ]

    again = harness.client.post(f"/v1/matches/{record['match_id']}/decision", json=decision)
    assert again.status_code == 409


def test_auto_approved_match_cannot_be_decided_again(harness: Harness) -> None:
    truth = next(t for t in harness.truths() if t.decision.value == "approve")
    record = harness.client.post("/v1/matches", json=harness.upload(truth)).json()
    decision = {"approve": True, "reviewer": "hamid"}
    response = harness.client.post(f"/v1/matches/{record['match_id']}/decision", json=decision)
    assert response.status_code == 409


def test_unknown_order_and_unknown_match(
    small_dataset: tuple[Path, Manifest], tmp_path: Path
) -> None:
    empty_erp = tmp_path / "empty_erp"
    empty_erp.mkdir()
    harness = Harness(small_dataset[0], tmp_path, erp_dir=empty_erp)
    truth = harness.truths()[0]
    response = harness.client.post("/v1/matches", json=harness.upload(truth))
    assert response.status_code == 422 and "purchase order" in response.text
    assert harness.client.get("/v1/matches/not-a-uuid").status_code == 404
