from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from belegfluss.checks.plausibility import PlausibilityIssue
from belegfluss.domain.discrepancies import Decision, DiscrepancyType
from belegfluss.domain.models import Model


class FindingJudgement(BaseModel):
    """What the adjudicator (LLM or deterministic baseline) proposes for one finding.

    Strict-mode schema for structured outputs: every field required, nullable instead of
    optional, no extra keys."""

    model_config = ConfigDict(extra="forbid")

    finding_id: str
    category: str = Field(description="One of the categories allowed for this finding.")
    clause_id: str | None = Field(description="Clause id of the cited evidence, e.g. '§ 4'.")
    quote: str | None = Field(description="Exact words copied from that clause.")
    explanation_de: str = Field(description="One or two sentences in German for the reviewer.")


class Adjudication(BaseModel):
    model_config = ConfigDict(extra="forbid")

    judgements: list[FindingJudgement]


class ReviewFinding(Model):
    finding_id: str
    type: DiscrepancyType
    position: int | None
    sku: str | None
    expected: str | None
    actual: str | None
    clause_id: str | None
    quote: str | None
    explanation_de: str
    verified: bool
    verification_note: str | None = None


class MatchResult(Model):
    invoice_number: str
    supplier_id: str
    po_number: str
    decision: Decision
    findings: list[ReviewFinding]
    issues: list[PlausibilityIssue]
    adjudicator: str
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
