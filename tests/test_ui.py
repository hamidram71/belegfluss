"""The review UI is served, is built from its TypeScript source, and never uses innerHTML."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from belegfluss.api.main import UI_DIR, create_app

REPO = Path(__file__).resolve().parent.parent


def test_ui_is_served_and_root_redirects() -> None:
    client = TestClient(create_app())
    page = client.get("/ui/")
    assert page.status_code == 200 and '<script type="module" src="app.js">' in page.text
    assert client.get("/ui/app.js").status_code == 200
    assert client.get("/ui/styles.css").status_code == 200
    root = client.get("/", follow_redirects=False)
    assert root.status_code in (302, 307) and root.headers["location"] == "/ui/"


def _code_without_comments(code: str) -> str:
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)
    return re.sub(r"(?m)^\s*//.*$", "", code)


def test_ui_never_writes_html_from_data() -> None:
    """Invoices come from outside; their text must never be parsed as HTML (XSS)."""
    for path in [REPO / "ui" / "src" / "app.ts", UI_DIR / "app.js"]:
        code = _code_without_comments(path.read_text(encoding="utf-8"))
        assert not re.search(
            r"\b(innerHTML|outerHTML|insertAdjacentHTML|document\.write)\b", code
        ), path


def test_compiled_ui_is_committed_next_to_its_source() -> None:
    """app.js must exist; CI rebuilds it and fails if it differs from the committed file."""
    assert (UI_DIR / "app.js").is_file()
    assert "FINDING_LABELS" in (UI_DIR / "app.js").read_text(encoding="utf-8")
