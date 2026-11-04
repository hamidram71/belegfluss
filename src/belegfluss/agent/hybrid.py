"""Hybrid adjudication: rules first, the LLM only where rules cannot decide (ADR 0008, update).

The evaluation on 200 sets showed the deterministic adjudicator matching or beating the LLM on
every category. The LLM is therefore asked only about findings the rules cannot settle:
a price finding whose price-list row could not be read, or any finding whose rule-based
proposal would not pass verification (for example, no supporting clause was retrieved).
On data the rules understand, this costs no model call at all.
"""

from __future__ import annotations

from belegfluss.agent.adjudicator import (
    PRICE_TYPES,
    DeterministicAdjudicator,
    FindingContext,
    LLMAdjudicator,
    list_price,
)
from belegfluss.agent.models import FindingJudgement
from belegfluss.agent.verify import verify
from belegfluss.extraction.llm import LLMUsage


def rules_can_decide(ctx: FindingContext, judgement: FindingJudgement) -> bool:
    if ctx.finding.type in PRICE_TYPES and list_price(ctx.evidence, ctx.finding.sku) is None:
        return False
    return verify(ctx, judgement).verified


class HybridAdjudicator:
    name = "hybrid"

    def __init__(self, llm: LLMAdjudicator) -> None:
        self.rules = DeterministicAdjudicator()
        self.llm = llm

    def adjudicate(
        self, contexts: list[FindingContext]
    ) -> tuple[dict[str, FindingJudgement], LLMUsage]:
        judgements, _ = self.rules.adjudicate(contexts)
        undecided = [c for c in contexts if not rules_can_decide(c, judgements[c.finding_id])]
        if not undecided:
            return judgements, LLMUsage()
        llm_judgements, usage = self.llm.adjudicate(undecided)
        judgements.update(llm_judgements)
        return judgements, usage
