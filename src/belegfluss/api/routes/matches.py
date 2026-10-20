"""Matching and the human review queue.

POST /v1/matches runs the whole pipeline for an uploaded invoice and delivery note: extraction,
order lookup in the ERP, rules, plausibility, contract retrieval, adjudication, verification
and the decision. Results that need a human appear in GET /v1/review-queue.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from belegfluss.agent.graph import match
from belegfluss.api.routes.documents import LLMDep, MasterDep, StoreDep
from belegfluss.config import Settings, get_settings
from belegfluss.contracts.store import VectorStoreUnavailableError
from belegfluss.erp import ErpOrders
from belegfluss.extraction.cii import EInvoiceParseError
from belegfluss.extraction.llm import LLMExtractionError, LLMNotConfiguredError
from belegfluss.extraction.llm_extract import ExtractionError
from belegfluss.extraction.pipeline import extract_delivery_note, extract_invoice
from belegfluss.runtime import create_match_graph
from belegfluss.storage.matches import AlreadyDecidedError, MatchRecord, MatchStore

router = APIRouter(tags=["matching"])

_graphs: dict[tuple[Any, ...], Any] = {}


def get_match_graph(
    settings: Annotated[Settings, Depends(get_settings)], master: MasterDep, llm: LLMDep
) -> Any:
    """Built once per configuration: building it indexes the contracts."""
    key = (
        str(settings.contracts_dir),
        settings.database_url,
        settings.embedding_model,
        settings.adjudicator,
        getattr(llm, "model", None),
    )
    if key not in _graphs:
        try:
            _graphs[key], _ = create_match_graph(settings, master, llm)
        except VectorStoreUnavailableError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return _graphs[key]


def get_erp(settings: Annotated[Settings, Depends(get_settings)]) -> ErpOrders:
    return ErpOrders.load(settings.erp_orders_dir)


def get_match_store(settings: Annotated[Settings, Depends(get_settings)]) -> MatchStore:
    return MatchStore(settings.matches_dir)


GraphDep = Annotated[Any, Depends(get_match_graph)]
ErpDep = Annotated[ErpOrders, Depends(get_erp)]
MatchStoreDep = Annotated[MatchStore, Depends(get_match_store)]


class MatchRequest(BaseModel):
    invoice_document_id: str
    delivery_note_document_id: str


class ReviewDecision(BaseModel):
    approve: bool
    reviewer: str = Field(min_length=1, max_length=100)
    comment: str | None = Field(default=None, max_length=2000)


@router.post("/v1/matches", status_code=status.HTTP_201_CREATED)
def create_match(
    request: MatchRequest,
    documents: StoreDep,
    matches: MatchStoreDep,
    master: MasterDep,
    llm: LLMDep,
    erp: ErpDep,
    graph: GraphDep,
) -> MatchRecord:
    invoice_bytes = documents.read(request.invoice_document_id)
    note_bytes = documents.read(request.delivery_note_document_id)
    if invoice_bytes is None or note_bytes is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    try:
        invoice = extract_invoice(invoice_bytes, master, llm)
        note = extract_delivery_note(note_bytes, master, llm)
    except LLMNotConfiguredError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except (EInvoiceParseError, ExtractionError, LLMExtractionError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    order = erp.get(invoice.document.po_number) or erp.get(note.document.po_number)
    if order is None:
        raise HTTPException(
            422,
            f"no purchase order {invoice.document.po_number!r} in the ERP export; "
            "the documents cannot be matched automatically",
        )
    result = match(
        graph,
        invoice.document,
        order,
        note.document,
        known_orders=erp.numbers(),
        warnings=invoice.warnings + note.warnings,
        security_flags=invoice.security_flags + note.security_flags,
    )
    return matches.add(result, request.invoice_document_id, request.delivery_note_document_id)


@router.get("/v1/matches/{match_id}")
def get_match(match_id: str, matches: MatchStoreDep) -> MatchRecord:
    record = matches.get(match_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "match not found")
    return record


@router.get("/v1/review-queue")
def review_queue(matches: MatchStoreDep) -> list[MatchRecord]:
    return matches.queue()


@router.post("/v1/matches/{match_id}/decision")
def decide(match_id: str, decision: ReviewDecision, matches: MatchStoreDep) -> MatchRecord:
    try:
        return matches.decide(match_id, decision.approve, decision.reviewer, decision.comment)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "match not found") from exc
    except AlreadyDecidedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
