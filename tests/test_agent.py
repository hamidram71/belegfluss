"""The agent's guarantees: the model only proposes, code verifies (ADR 0008)."""

from __future__ import annotations

import random
from typing import Any

import pytest
from pydantic import BaseModel

from belegfluss.agent.adjudicator import DeterministicAdjudicator, LLMAdjudicator
from belegfluss.agent.graph import build_match_graph, match
from belegfluss.agent.models import Adjudication, FindingJudgement
from belegfluss.contracts.embeddings import HashingEmbedder
from belegfluss.contracts.retrieval import ContractRetriever
from belegfluss.contracts.store import InMemoryVectorStore
from belegfluss.domain.discrepancies import Decision, DiscrepancyType
from belegfluss.extraction.llm import LLMResult, LLMUsage
from belegfluss.master_data import MasterData
from belegfluss.security.pii import mask_text
from belegfluss.synth.render_pdf import render_contract_pdf
from belegfluss.synth.scenarios import GeneratedSet, generate_set
from belegfluss.synth.world import World


@pytest.fixture(scope="module")
def retriever(world: World) -> ContractRetriever:
    r = ContractRetriever(InMemoryVectorStore(), HashingEmbedder())
    for supplier in world.suppliers:
        r.index_pdf(render_contract_pdf(supplier.contract))
    return r


class ScriptedLLM:
    """Returns a fixed adjudication and records what it was sent."""

    def __init__(self, judgements: list[FindingJudgement]) -> None:
        self.judgements = judgements
        self.prompts: list[str] = []

    def extract(
        self,
        schema: type[BaseModel],
        instructions: str,
        text: str | None = None,
        images: list[bytes] | None = None,
    ) -> LLMResult[Any]:
        self.prompts.append(text or "")
        return LLMResult(parsed=Adjudication(judgements=self.judgements), usage=LLMUsage())


def _set_with(world: World, kind: DiscrepancyType) -> GeneratedSet:
    rng = random.Random(5)
    for index in range(1, 400):
        g = generate_set(rng, world, index, forced=[kind])
        if [d.type for d in g.discrepancies] == [kind]:
            return g
    raise AssertionError(kind)


def _run(
    world: World,
    master: MasterData,
    retriever: ContractRetriever,
    g: GeneratedSet,
    adjudicator: Any,
) -> Any:
    graph = build_match_graph(master, retriever, adjudicator)
    return match(graph, g.invoice, g.purchase_order, g.delivery_note)


def test_clean_set_is_approved_without_calling_the_model(
    world: World, master: MasterData, retriever: ContractRetriever
) -> None:
    llm = ScriptedLLM([])
    g = generate_set(random.Random(3), world, 1, p_discrepant=0.0)
    result = _run(world, master, retriever, g, LLMAdjudicator(llm))
    assert result.decision is Decision.APPROVE and llm.prompts == []


@pytest.mark.parametrize(
    "kind", [DiscrepancyType.PRICE_ABOVE_CONTRACT, DiscrepancyType.VOLUME_DISCOUNT_MISSING]
)
def test_deterministic_baseline_classifies_and_cites(
    world: World, master: MasterData, retriever: ContractRetriever, kind: DiscrepancyType
) -> None:
    g = _set_with(world, kind)
    result = _run(world, master, retriever, g, DeterministicAdjudicator())
    label = g.discrepancies[0]
    [finding] = result.findings
    assert (finding.type, finding.clause_id, finding.verified) == (kind, label.clause_id, True)


def test_invented_clause_is_rejected(
    world: World, master: MasterData, retriever: ContractRetriever
) -> None:
    g = _set_with(world, DiscrepancyType.PAYMENT_TERMS_DEVIATION)
    llm = ScriptedLLM(
        [
            FindingJudgement(
                finding_id="F1",
                category="payment_terms_deviation",
                clause_id="§ 99",
                quote="Zahlbar sofort",
                explanation_de="x",
            )
        ]
    )
    [finding] = _run(world, master, retriever, g, LLMAdjudicator(llm)).findings
    assert not finding.verified and "not in the evidence" in (finding.verification_note or "")


def test_quote_not_in_clause_is_rejected(
    world: World, master: MasterData, retriever: ContractRetriever
) -> None:
    g = _set_with(world, DiscrepancyType.PAYMENT_TERMS_DEVIATION)
    clause = g.supplier.contract.payment_terms_clause_id
    llm = ScriptedLLM(
        [
            FindingJudgement(
                finding_id="F1",
                category="payment_terms_deviation",
                clause_id=clause,
                quote="Skonto wird nie gewährt",
                explanation_de="x",
            )
        ]
    )
    [finding] = _run(world, master, retriever, g, LLMAdjudicator(llm)).findings
    assert not finding.verified and "quote" in (finding.verification_note or "")


def test_price_category_contradicting_the_numbers_is_rejected(
    world: World, master: MasterData, retriever: ContractRetriever
) -> None:
    g = _set_with(world, DiscrepancyType.PRICE_ABOVE_CONTRACT)
    row = next(c for c in g.supplier.contract.clauses if c.clause_id == "Anlage 1")
    sku = g.discrepancies[0].sku
    line = next(line for line in row.text.splitlines() if sku and sku in line)
    llm = ScriptedLLM(
        [
            FindingJudgement(
                finding_id="F1",
                category="volume_discount_missing",
                clause_id="Anlage 1",
                quote=sku,
                explanation_de="x",
            )
        ]
    )
    [finding] = _run(world, master, retriever, g, LLMAdjudicator(llm)).findings
    assert line and not finding.verified
    assert finding.type is DiscrepancyType.PRICE_ABOVE_CONTRACT  # rules' category is kept
    assert result_is_review(_run(world, master, retriever, g, LLMAdjudicator(llm)))


def result_is_review(result: Any) -> bool:
    return bool(result.decision is Decision.REVIEW)


def test_category_outside_the_allowed_set_is_rejected(
    world: World, master: MasterData, retriever: ContractRetriever
) -> None:
    g = _set_with(world, DiscrepancyType.WRONG_VAT_RATE)
    llm = ScriptedLLM(
        [
            FindingJudgement(
                finding_id="F1",
                category="bank_details_changed",
                clause_id=None,
                quote=None,
                explanation_de="x",
            )
        ]
    )
    [finding] = _run(world, master, retriever, g, LLMAdjudicator(llm)).findings
    assert not finding.verified and finding.type is DiscrepancyType.WRONG_VAT_RATE


def test_adjudication_prompt_contains_no_iban(
    world: World, master: MasterData, retriever: ContractRetriever
) -> None:
    g = _set_with(world, DiscrepancyType.BANK_DETAILS_CHANGED)
    llm = ScriptedLLM([])
    _run(world, master, retriever, g, LLMAdjudicator(llm))
    assert llm.prompts and g.invoice.seller.iban
    assert g.invoice.seller.iban not in llm.prompts[0].replace(" ", "")


def test_mask_text() -> None:
    masked = mask_text("IBAN DE89 3704 0044 0532 0130 00, rechnung@firma.example, +49 711 123456")
    assert "0532" not in masked and "DE** **** 3000" in masked
    assert "[email]" in masked and "[phone]" in masked
