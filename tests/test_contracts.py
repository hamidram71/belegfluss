from __future__ import annotations

import os
import random
from types import SimpleNamespace
from typing import Any

import pytest

from belegfluss.contracts.chunking import ContractParseError, chunk_contract
from belegfluss.contracts.embeddings import HashingEmbedder, OpenAIEmbedder
from belegfluss.contracts.retrieval import ContractRetriever
from belegfluss.contracts.store import InMemoryVectorStore, PgVectorStore, VectorStore
from belegfluss.domain.discrepancies import DiscrepancyType
from belegfluss.domain.money import format_unit_price_de
from belegfluss.synth.render_pdf import render_contract_pdf, render_invoice_pdf
from belegfluss.synth.scenarios import generate_set
from belegfluss.synth.world import World

PG_DSN = os.environ.get("BELEGFLUSS_TEST_PG_DSN")


def _retriever(world: World, store: VectorStore) -> ContractRetriever:
    retriever = ContractRetriever(store, HashingEmbedder())
    for supplier in world.suppliers:
        retriever.index_pdf(render_contract_pdf(supplier.contract))
    return retriever


def test_chunks_match_the_contract_clauses_and_prices(world: World) -> None:
    for supplier in world.suppliers:
        contract = supplier.contract
        chunks = chunk_contract(render_contract_pdf(contract))
        clause_chunks = [c for c in chunks if c.clause_id.startswith("§")]
        assert [c.clause_id for c in clause_chunks] == [
            c.clause_id for c in contract.clauses if c.clause_id.startswith("§")
        ]
        rows = {c.chunk_id.rsplit("#", 1)[1]: c.text for c in chunks if c.clause_id == "Anlage 1"}
        assert set(rows) == {a.sku for a in contract.price_agreements}
        for agreement in contract.price_agreements:
            assert format_unit_price_de(agreement.unit_price) in rows[agreement.sku]
        assert all(c.contract_number == contract.contract_number for c in chunks)
        assert not any("Heilbronn, den" in c.text for c in chunks)  # signature block excluded


def test_non_contract_pdf_is_rejected(world: World) -> None:
    invoice = generate_set(random.Random(1), world, 1).invoice
    with pytest.raises(ContractParseError):
        chunk_contract(render_invoice_pdf(invoice))


@pytest.mark.parametrize(
    "kind",
    [
        DiscrepancyType.PRICE_ABOVE_CONTRACT,
        DiscrepancyType.VOLUME_DISCOUNT_MISSING,
        DiscrepancyType.PAYMENT_TERMS_DEVIATION,
        DiscrepancyType.QUANTITY_EXCEEDS_DELIVERY,
        DiscrepancyType.BANK_DETAILS_CHANGED,
    ],
)
def test_evidence_contains_the_labelled_clause(world: World, kind: DiscrepancyType) -> None:
    retriever = _retriever(world, InMemoryVectorStore())
    rng = random.Random(21)
    found = 0
    for index in range(1, 300):
        generated = generate_set(rng, world, index, forced=[kind])
        label = next((d for d in generated.discrepancies if d.type is kind), None)
        if label is None or label.clause_id is None:
            continue
        # Rules report a missing volume discount as a price finding (ADR 0007).
        finding = (
            label.model_copy(update={"type": DiscrepancyType.PRICE_ABOVE_CONTRACT})
            if kind is DiscrepancyType.VOLUME_DISCOUNT_MISSING
            else label
        )
        evidence = retriever.evidence(generated.supplier.contract.contract_number, finding)
        assert label.clause_id in [e.chunk.clause_id for e in evidence]
        found += 1
        if found == 5:
            return
    raise AssertionError(f"too few {kind} examples")


def test_price_row_is_found_by_exact_article_number(world: World) -> None:
    retriever = _retriever(world, InMemoryVectorStore())
    contract = world.suppliers[0].contract
    sku = contract.price_agreements[-1].sku
    best = retriever.search(contract.contract_number, "Preis", k=1, keyword=sku)[0]
    assert best.keyword_hit and sku in best.chunk.text


def test_search_never_crosses_contracts(world: World) -> None:
    retriever = _retriever(world, InMemoryVectorStore())
    number = world.suppliers[1].contract.contract_number
    results = retriever.search(number, "Zahlungsbedingungen Skonto", k=20)
    assert results and all(r.chunk.contract_number == number for r in results)


def test_openai_embedder_batches_requests() -> None:
    calls: list[dict[str, Any]] = []

    def create(**kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.1, 0.2]) for _ in kwargs["input"]]
        )

    client = SimpleNamespace(embeddings=SimpleNamespace(create=create))
    vectors = OpenAIEmbedder(client, model="m", dimensions=2).embed([f"t{i}" for i in range(300)])
    assert len(vectors) == 300 and [len(c["input"]) for c in calls] == [128, 128, 44]
    assert calls[0]["dimensions"] == 2 and calls[0]["model"] == "m"


@pytest.mark.skipif(PG_DSN is None, reason="set BELEGFLUSS_TEST_PG_DSN to run against pgvector")
def test_pgvector_ranks_like_the_in_memory_store(world: World) -> None:
    assert PG_DSN is not None
    pg = PgVectorStore(PG_DSN, dimensions=512, table="test_contract_chunks")
    pg.drop()
    pg = PgVectorStore(PG_DSN, dimensions=512, table="test_contract_chunks")
    in_pg, in_memory = _retriever(world, pg), _retriever(world, InMemoryVectorStore())
    assert pg.count() == in_memory.store.count()
    number = world.suppliers[2].contract.contract_number
    for query, keyword in [
        ("Zahlungsbedingungen Skonto", None),
        ("Bankverbindung", None),
        ("Preis", world.suppliers[2].contract.price_agreements[0].sku),
    ]:
        a = [r.chunk.chunk_id for r in in_pg.search(number, query, k=3, keyword=keyword)]
        b = [r.chunk.chunk_id for r in in_memory.search(number, query, k=3, keyword=keyword)]
        assert a == b
    pg.drop()


def test_unreachable_database_fails_fast_with_a_clear_message() -> None:
    import time

    from belegfluss.contracts.store import VectorStoreUnavailableError

    start = time.perf_counter()
    with pytest.raises(VectorStoreUnavailableError, match="docker compose up"):
        PgVectorStore("postgresql://u:p@127.0.0.1:1/none", dimensions=8)
    assert time.perf_counter() - start < 10
