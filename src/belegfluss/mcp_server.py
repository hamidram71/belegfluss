"""MCP server: lets AI assistants (Claude Desktop, IDEs) look into Belegfluss.

Deliberately read-only. An assistant can list the review queue, read a match and search a
framework contract, but it cannot approve or reject anything: payment decisions stay with a
human in the review queue (ADR 0009). Identifiers such as IBANs are masked in everything this
server returns.

Run with ``belegfluss-mcp`` (stdio transport).
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import MCPServer

from belegfluss.config import Settings, get_settings
from belegfluss.contracts.retrieval import ContractRetriever
from belegfluss.runtime import create_retriever
from belegfluss.security.pii import mask_text
from belegfluss.storage.matches import MatchRecord, MatchStore

INSTRUCTIONS = (
    "Read-only access to Belegfluss, which matches supplier invoices against purchase orders, "
    "delivery notes and framework contracts. Use list_review_queue to see what needs a human, "
    "get_match for the findings of one match, and search_contract to quote contract clauses. "
    "Approving or rejecting is not possible here; reviewers do that in the review queue."
)


def _masked(payload: Any) -> Any:
    return json.loads(mask_text(json.dumps(payload, ensure_ascii=False, default=str)))


def _summary(record: MatchRecord) -> dict[str, Any]:
    result = record.result
    return {
        "match_id": record.match_id,
        "status": record.status.value,
        "invoice_number": result.invoice_number,
        "supplier_id": result.supplier_id,
        "po_number": result.po_number,
        "findings": [f.type.value for f in result.findings],
        "issues": [i.code.value for i in result.issues],
    }


def build_server(settings: Settings | None = None) -> MCPServer:
    settings = settings or get_settings()
    store = MatchStore(settings.matches_dir)
    retriever: dict[str, ContractRetriever] = {}

    server = MCPServer(name="belegfluss", instructions=INSTRUCTIONS)

    @server.tool(description="Matches waiting for a human decision, oldest first.")
    def list_review_queue() -> list[dict[str, Any]]:
        return [_masked(_summary(r)) for r in store.queue()]

    @server.tool(description="Full result of one match: findings, cited clauses, explanations.")
    def get_match(match_id: str) -> dict[str, Any]:
        record = store.get(match_id)
        if record is None:
            raise ValueError(f"no match {match_id!r}")
        payload: dict[str, Any] = _masked(record.model_dump(mode="json"))
        return payload

    @server.tool(description="Search one framework contract, e.g. for 'Skonto' or an article.")
    def search_contract(contract_number: str, query: str, k: int = 3) -> list[dict[str, Any]]:
        if "index" not in retriever:
            retriever["index"] = create_retriever(settings)
        hits = retriever["index"].search(contract_number, query, k=max(1, min(k, 10)))
        return [
            {"clause_id": h.chunk.clause_id, "text": h.chunk.text, "score": round(h.similarity, 3)}
            for h in hits
        ]

    return server


def main() -> None:
    build_server().run("stdio")


if __name__ == "__main__":
    main()
