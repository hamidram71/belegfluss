"""The matching workflow as a LangGraph state graph.

    rules -> plausibility -> (needs evidence?) -> retrieve -> adjudicate -> verify -> decide
                                    \\-------------- no findings -----------------------/

It is a *workflow* with one model step, not an open-ended agent loop: every path is known in
advance, which keeps it testable and auditable (ADR 0008). Sets without findings never reach
the model.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from belegfluss.agent.adjudicator import Adjudicator, FindingContext
from belegfluss.agent.models import FindingJudgement, MatchResult, ReviewFinding
from belegfluss.agent.verify import verify
from belegfluss.checks.plausibility import PlausibilityIssue, check_plausibility
from belegfluss.checks.rules import run_rules
from belegfluss.contracts.retrieval import ContractRetriever
from belegfluss.domain.discrepancies import Decision, Discrepancy
from belegfluss.domain.models import DeliveryNote, Invoice, PurchaseOrder
from belegfluss.extraction.llm import LLMUsage
from belegfluss.master_data import MasterData


class MatchState(TypedDict, total=False):
    invoice: Invoice
    order: PurchaseOrder
    delivery: DeliveryNote
    known_orders: set[str]
    warnings: list[str]
    security_flags: list[str]
    findings: list[Discrepancy]
    issues: list[PlausibilityIssue]
    contexts: list[FindingContext]
    judgements: dict[str, FindingJudgement]
    usage: LLMUsage
    reviewed: list[ReviewFinding]
    result: MatchResult


def build_match_graph(
    master: MasterData, retriever: ContractRetriever, adjudicator: Adjudicator
) -> Any:
    def rules(state: MatchState) -> MatchState:
        return {"findings": run_rules(state["invoice"], state["order"], state["delivery"], master)}

    def plausibility(state: MatchState) -> MatchState:
        issues = check_plausibility(
            state["invoice"],
            state["delivery"],
            state.get("known_orders", {state["order"].po_number}),
            warnings=state.get("warnings"),
            security_flags=state.get("security_flags"),
        )
        return {"issues": issues}

    def needs_evidence(state: MatchState) -> str:
        return "retrieve" if state["findings"] else "decide"

    def retrieve(state: MatchState) -> MatchState:
        contract = state["order"].contract_number
        contexts = [
            FindingContext(
                finding_id=f"F{i}",
                finding=finding,
                evidence=retriever.evidence(contract, finding) if contract else [],
            )
            for i, finding in enumerate(state["findings"], start=1)
        ]
        return {"contexts": contexts}

    def adjudicate(state: MatchState) -> MatchState:
        judgements, usage = adjudicator.adjudicate(state["contexts"])
        return {"judgements": judgements, "usage": usage}

    def verify_all(state: MatchState) -> MatchState:
        judgements = state.get("judgements", {})
        return {"reviewed": [verify(c, judgements.get(c.finding_id)) for c in state["contexts"]]}

    def decide(state: MatchState) -> MatchState:
        reviewed = state.get("reviewed", [])
        issues = state.get("issues", [])
        usage = state.get("usage", LLMUsage())
        invoice = state["invoice"]
        result = MatchResult(
            invoice_number=invoice.invoice_number,
            supplier_id=invoice.seller.party_id,
            po_number=state["order"].po_number,
            decision=Decision.REVIEW if reviewed or issues else Decision.APPROVE,
            findings=reviewed,
            issues=issues,
            adjudicator=adjudicator.name,
            llm_input_tokens=usage.input_tokens,
            llm_output_tokens=usage.output_tokens,
        )
        return {"result": result}

    graph = StateGraph(MatchState)
    graph.add_node("rules", rules)
    graph.add_node("plausibility", plausibility)
    graph.add_node("retrieve", retrieve)
    graph.add_node("adjudicate", adjudicate)
    graph.add_node("verify", verify_all)
    graph.add_node("decide", decide)
    graph.add_edge(START, "rules")
    graph.add_edge("rules", "plausibility")
    graph.add_conditional_edges("plausibility", needs_evidence, ["retrieve", "decide"])
    graph.add_edge("retrieve", "adjudicate")
    graph.add_edge("adjudicate", "verify")
    graph.add_edge("verify", "decide")
    graph.add_edge("decide", END)
    return graph.compile()


def match(
    graph: Any,
    invoice: Invoice,
    order: PurchaseOrder,
    delivery: DeliveryNote,
    known_orders: set[str] | None = None,
    warnings: list[str] | None = None,
    security_flags: list[str] | None = None,
) -> MatchResult:
    state: MatchState = {"invoice": invoice, "order": order, "delivery": delivery}
    if known_orders is not None:
        state["known_orders"] = known_orders
    if warnings:
        state["warnings"] = warnings
    if security_flags:
        state["security_flags"] = security_flags
    final = graph.invoke(state)
    result: MatchResult = final["result"]
    return result
