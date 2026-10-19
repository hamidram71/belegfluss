from __future__ import annotations

import random
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from belegfluss.api.main import create_app
from belegfluss.config import Settings, get_settings
from belegfluss.synth.render_pdf import render_invoice_pdf
from belegfluss.synth.render_xml import render_invoice_xml
from belegfluss.synth.scenarios import generate_set
from belegfluss.synth.world import World


@pytest.fixture()
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(storage_dir=tmp_path, max_upload_mb=1)
    with TestClient(app) as test_client:
        yield test_client


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_upload_and_fetch_xml_invoice(client: TestClient, world: World) -> None:
    xml = render_invoice_xml(generate_set(random.Random(1), world, 1).invoice)
    response = client.post("/v1/documents", files={"file": ("rechnung.xml", xml)})
    assert response.status_code == 201
    body = response.json()
    assert body["format"] == "xrechnung_cii"
    assert body["size_bytes"] == len(xml)

    fetched = client.get(f"/v1/documents/{body['document_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["sha256"] == body["sha256"]


def test_upload_pdf_ignores_misleading_filename(client: TestClient, world: World) -> None:
    pdf = render_invoice_pdf(generate_set(random.Random(2), world, 2).invoice)
    response = client.post("/v1/documents", files={"file": ("invoice.xml", pdf)})
    assert response.status_code == 201
    assert response.json()["format"] == "pdf"


def test_rejects_unsupported_and_oversized_files(client: TestClient) -> None:
    assert client.post("/v1/documents", files={"file": ("a.txt", b"hello")}).status_code == 415
    assert client.post("/v1/documents", files={"file": ("e.pdf", b"")}).status_code == 422
    big = b"%PDF-1.7\n" + b"0" * (1024 * 1024 + 1)
    assert client.post("/v1/documents", files={"file": ("big.pdf", big)}).status_code == 413


def test_unknown_or_malformed_id_returns_404(client: TestClient) -> None:
    assert client.get("/v1/documents/00000000-0000-0000-0000-000000000000").status_code == 404
    assert client.get("/v1/documents/../../etc/passwd").status_code == 404
