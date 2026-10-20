"""Verify an adjudicator's proposal before it counts (ADR 0008).

A proposal is accepted only if (1) its category is allowed for the finding, (2) the cited
clause was among the retrieved evidence, (3) the quote occurs verbatim in that clause and
(4) for price findings, the numbers agree with the price list. Otherwise the finding keeps the
rules' category and is marked unverified, which always means human review.
"""

from __future__ import annotations

import re
from decimal import Decimal

from belegfluss.agent.adjudicator import (
    CONTRACT_BASED,
    OPTIONAL_CITATION,
    PRICE_TYPES,
    FindingContext,
    allowed_categories,
    list_price,
)
from belegfluss.agent.models import FindingJudgement, ReviewFinding
from belegfluss.domain.discrepancies import DiscrepancyType


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def verify(ctx: FindingContext, judgement: FindingJudgement | None) -> ReviewFinding:
    f = ctx.finding
    base = {
        "finding_id": ctx.finding_id,
        "position": f.position,
        "sku": f.sku,
        "expected": f.expected,
        "actual": f.actual,
    }

    def reject(note: str) -> ReviewFinding:
        return ReviewFinding(
            **base,
            type=f.type,
            clause_id=None,
            quote=None,
            explanation_de=judgement.explanation_de if judgement else "",
            verified=False,
            verification_note=note,
        )

    if judgement is None:
        return reject("no judgement returned")
    try:
        category = DiscrepancyType(judgement.category)
    except ValueError:
        return reject(f"unknown category {judgement.category!r}")
    if category not in allowed_categories(f):
        return reject(f"category {category.value} not allowed for {f.type.value}")

    cited = judgement.clause_id is not None
    if category in CONTRACT_BASED or (category in OPTIONAL_CITATION and cited):
        # Several chunks can share a clause id (one per price-list row), so the quote is
        # checked against every retrieved chunk of that clause; for a price finding the chunk
        # must also be the row of the finding's own article.
        candidates = [
            h.chunk
            for h in ctx.evidence
            if h.chunk.clause_id == judgement.clause_id
            and (
                category not in PRICE_TYPES
                or not h.chunk.clause_id.startswith("Anlage")
                or (f.sku is not None and f.sku in h.chunk.text)
            )
        ]
        if not candidates:
            return reject(f"cited clause {judgement.clause_id!r} was not in the evidence")
        quote = _norm(judgement.quote or "")
        if not quote or not any(quote in _norm(c.text) for c in candidates):
            return reject("quote does not occur in the cited clause")
        if category in PRICE_TYPES:
            agreed = list_price(ctx.evidence, f.sku)
            if agreed is not None and f.actual is not None:
                invoiced = Decimal(f.actual)
                if category is DiscrepancyType.VOLUME_DISCOUNT_MISSING and invoiced != agreed:
                    return reject(f"invoiced {invoiced} is not the list price {agreed}")
                if (
                    category is DiscrepancyType.PRICE_ABOVE_CONTRACT
                    and invoiced == agreed
                    and (f.expected is not None and Decimal(f.expected) < agreed)
                ):
                    return reject("invoice charges the list price: discount case, not a raise")

    return ReviewFinding(
        **base,
        type=category,
        clause_id=judgement.clause_id,
        quote=judgement.quote,
        explanation_de=judgement.explanation_de,
        verified=True,
    )
