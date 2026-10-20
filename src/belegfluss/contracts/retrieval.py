"""Find the contract clause that is evidence for a finding.

Queries are fixed templates per discrepancy type, not free text written by a model: retrieval
is then reproducible, testable and measurable (hit@k per type), and the LLM's job is reduced
to judging the evidence it is given (ADR 0007).
"""

from __future__ import annotations

from pathlib import Path

from belegfluss.contracts.chunking import Chunk, chunk_contract
from belegfluss.contracts.embeddings import Embedder
from belegfluss.contracts.store import ScoredChunk, VectorStore
from belegfluss.domain.discrepancies import Discrepancy, DiscrepancyType

QUERY_TEMPLATES: dict[DiscrepancyType, str] = {
    DiscrepancyType.PRICE_ABOVE_CONTRACT: (
        "Preisliste vereinbarter Nettopreis für Artikel {sku} Festpreis"
    ),
    DiscrepancyType.VOLUME_DISCOUNT_MISSING: (
        "Rabatt ab einer Bestellmenge von Einheiten je Bestellposition, Nachlass auf den "
        "Einzelpreis"
    ),
    DiscrepancyType.QUANTITY_EXCEEDS_DELIVERY: (
        "Teillieferungen: berechnet werden nur gelieferte, per Lieferschein bestätigte Mengen"
    ),
    DiscrepancyType.ITEM_NOT_ORDERED: (
        "Zuschläge, Versand, Fracht- und Verpackungspauschalen nur nach schriftlicher Vereinbarung"
    ),
    DiscrepancyType.PAYMENT_TERMS_DEVIATION: (
        "Zahlungsbedingungen: Zahlungsfrist in Tagen netto, Skonto, abweichende Bedingungen "
        "auf Rechnungen"
    ),
    DiscrepancyType.BANK_DETAILS_CHANGED: (
        "Zahlungen nur auf das hinterlegte Konto, Änderung der Bankverbindung, IBAN"
    ),
}


class ContractRetriever:
    def __init__(self, store: VectorStore, embedder: Embedder) -> None:
        self.store = store
        self.embedder = embedder

    def index_chunks(self, chunks: list[Chunk]) -> int:
        if chunks:
            self.store.upsert(chunks, self.embedder.embed([c.text for c in chunks]))
        return len(chunks)

    def index_pdf(self, pdf: bytes) -> int:
        return self.index_chunks(chunk_contract(pdf))

    def index_directory(self, directory: Path) -> int:
        return sum(self.index_pdf(p.read_bytes()) for p in sorted(directory.glob("*.pdf")))

    def search(
        self, contract_number: str, query: str, k: int = 3, keyword: str | None = None
    ) -> list[ScoredChunk]:
        vector = self.embedder.embed([query])[0]
        return self.store.search(contract_number, vector, k, keyword)

    def evidence(self, contract_number: str, finding: Discrepancy, k: int = 3) -> list[ScoredChunk]:
        """Candidate clauses for a finding. A price finding retrieves both the price-list row
        and the volume-discount clause, because the agent must decide between the two."""
        kinds = [finding.type]
        if finding.type is DiscrepancyType.PRICE_ABOVE_CONTRACT:
            kinds.append(DiscrepancyType.VOLUME_DISCOUNT_MISSING)
        per_query: list[list[ScoredChunk]] = []
        for kind in kinds:
            template = QUERY_TEMPLATES.get(kind)
            if template is None:
                continue
            keyword = finding.sku if kind is DiscrepancyType.PRICE_ABOVE_CONTRACT else None
            per_query.append(
                self.search(contract_number, template.format(sku=finding.sku or ""), k, keyword)
            )
        # Interleave by rank: each query's best hit comes before any query's second hit, so
        # for a price finding the price row and the discount clause lead the list.
        results: dict[str, ScoredChunk] = {}
        for rank in range(k):
            for hits in per_query:
                if rank < len(hits):
                    results.setdefault(hits[rank].chunk.chunk_id, hits[rank])
        return list(results.values())
