"""The MCP server, tested through a real MCP client connected in-process."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import anyio
from mcp import Client

from belegfluss.agent.adjudicator import DeterministicAdjudicator
from belegfluss.agent.graph import build_match_graph, match
from belegfluss.config import Settings
from belegfluss.contracts.embeddings import HashingEmbedder
from belegfluss.contracts.retrieval import ContractRetriever
from belegfluss.contracts.store import InMemoryVectorStore
from belegfluss.domain.discrepancies import DiscrepancyType
from belegfluss.master_data import MasterData
from belegfluss.mcp_server import build_server
from belegfluss.storage.matches import MatchStore
from belegfluss.synth.render_pdf import render_contract_pdf
from belegfluss.synth.scenarios import generate_set
from belegfluss.synth.world import World


def _call(settings: Settings, tool: str, args: dict[str, Any]) -> Any:
    async def run() -> Any:
        async with Client(build_server(settings)) as client:
            if tool == "__list__":
                return [t.name for t in (await client.list_tools()).tools]
            result = await client.call_tool(tool, args)
            assert not result.is_error, result
            return result.structured_content

    return anyio.run(run)


def _settings(tmp_path: Path, world: World) -> Settings:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    for supplier in world.suppliers:
        number = supplier.contract.contract_number
        (contracts / f"{number}.pdf").write_bytes(render_contract_pdf(supplier.contract))
    return Settings(matches_dir=tmp_path / "matches", contracts_dir=contracts)


def test_server_is_read_only(tmp_path: Path, world: World) -> None:
    tools = _call(_settings(tmp_path, world), "__list__", {})
    assert set(tools) == {"list_review_queue", "get_match", "search_contract"}


def test_queue_and_match_are_returned_with_masked_iban(
    tmp_path: Path, world: World, master: MasterData
) -> None:
    settings = _settings(tmp_path, world)
    retriever = ContractRetriever(InMemoryVectorStore(), HashingEmbedder())
    retriever.index_directory(settings.contracts_dir)
    graph = build_match_graph(master, retriever, DeterministicAdjudicator())
    g = generate_set(random.Random(5), world, 1, forced=[DiscrepancyType.BANK_DETAILS_CHANGED])
    record = MatchStore(settings.matches_dir).add(
        match(graph, g.invoice, g.purchase_order, g.delivery_note)
    )
    queue = _call(settings, "list_review_queue", {})
    assert [q["match_id"] for q in queue["result"]] == [record.match_id]
    detail = _call(settings, "get_match", {"match_id": record.match_id})
    text = json.dumps(detail)
    assert "bank_details_changed" in text
    assert g.invoice.seller.iban and g.invoice.seller.iban not in text.replace(" ", "")


def test_search_contract(tmp_path: Path, world: World) -> None:
    settings = _settings(tmp_path, world)
    number = world.suppliers[0].contract.contract_number
    hits = _call(settings, "search_contract", {"contract_number": number, "query": "Skonto"})
    assert hits["result"] and all("clause_id" in h for h in hits["result"])
