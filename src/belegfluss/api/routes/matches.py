"""Matching and the human review queue.

POST /v1/matches runs the whole pipeline for an uploaded invoice and delivery note: extraction,
order lookup in the ERP, rules, plausibility, contract retrieval, adjudication, verification
and the decision. Results that need a human appear in GET /v1/review-queue.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from belegfluss.agent.graph import match
from belegfluss.agent.models import TraceStep
from belegfluss.api.routes.documents import LLMDep, MasterDep, StoreDep
from belegfluss.config import Settings, get_settings
from belegfluss.contracts.store import VectorStoreUnavailableError
from belegfluss.erp import ErpOrders
from belegfluss.extraction.cii import EInvoiceParseError
from belegfluss.extraction.llm import LLMExtractionError, LLMNotConfiguredError, StructuredLLM
from belegfluss.extraction.llm_extract import ExtractionError
from belegfluss.extraction.pipeline import Extracted, extract_delivery_note, extract_invoice
from belegfluss.master_data import MasterData
from belegfluss.runtime import create_match_graph
from belegfluss.storage.matches import AlreadyDecidedError, MatchRecord, MatchStore

router = APIRouter(tags=["matching"])
log = logging.getLogger("belegfluss.matching")

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
        except (VectorStoreUnavailableError, LLMNotConfiguredError) as exc:
            # Configuration problems get a clear 503 with what to fix, never an opaque 500.
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return _graphs[key]


def get_erp(settings: Annotated[Settings, Depends(get_settings)]) -> ErpOrders:
    return ErpOrders.load(settings.erp_orders_dir)


def get_match_store(settings: Annotated[Settings, Depends(get_settings)]) -> MatchStore:
    return MatchStore(settings.matches_dir)


GraphDep = Annotated[Any, Depends(get_match_graph)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
ErpDep = Annotated[ErpOrders, Depends(get_erp)]
MatchStoreDep = Annotated[MatchStore, Depends(get_match_store)]


class MatchRequest(BaseModel):
    invoice_document_id: str
    delivery_note_document_id: str


class ReviewDecision(BaseModel):
    approve: bool
    reviewer: str = Field(min_length=1, max_length=100)
    comment: str | None = Field(default=None, max_length=2000)


def _timed_extract(
    kind: str, data: bytes, master: MasterData, llm: StructuredLLM | None
) -> tuple[Extracted[Any], TraceStep]:
    start = time.perf_counter()
    extract = extract_invoice if kind == "invoice" else extract_delivery_note
    result: Extracted[Any] = extract(data, master, llm)
    step = TraceStep(
        step=f"extract_{kind}",
        duration_ms=round((time.perf_counter() - start) * 1000),
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
        detail=result.method.value,
    )
    return result, step


def estimated_cost(settings: Settings, input_tokens: int, output_tokens: int) -> float | None:
    if settings.llm_input_usd_per_mtok is None or settings.llm_output_usd_per_mtok is None:
        return None
    return round(
        (
            input_tokens * settings.llm_input_usd_per_mtok
            + output_tokens * settings.llm_output_usd_per_mtok
        )
        / 1_000_000,
        6,
    )


def run_match(
    invoice_bytes: bytes,
    note_bytes: bytes,
    invoice_id: str,
    note_id: str,
    *,
    settings: Settings,
    matches: MatchStore,
    master: MasterData,
    llm: StructuredLLM | None,
    erp: ErpOrders,
    graph: Any,
) -> MatchRecord:
    """The whole pipeline for one invoice and delivery note; shared by every entry point."""
    try:
        invoice, invoice_step = _timed_extract("invoice", invoice_bytes, master, llm)
        note, note_step = _timed_extract("delivery_note", note_bytes, master, llm)
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
        prior_steps=[invoice_step, note_step],
    )
    result = result.model_copy(
        update={
            "estimated_cost_usd": estimated_cost(
                settings, result.llm_input_tokens, result.llm_output_tokens
            )
        }
    )
    record = matches.add(result, invoice_id, note_id)
    # One structured line per match: queryable in Log Analytics (see infra/README.md).
    log.info(
        json.dumps(
            {
                "event": "match",
                "match_id": record.match_id,
                "decision": result.decision.value,
                "findings": [f.type.value for f in result.findings],
                "issues": [i.code.value for i in result.issues],
                "duration_ms": result.duration_ms,
                "input_tokens": result.llm_input_tokens,
                "output_tokens": result.llm_output_tokens,
                "estimated_cost_usd": result.estimated_cost_usd,
                "steps": {step.step: step.duration_ms for step in result.trace},
            }
        )
    )
    return record


@router.post("/v1/matches", status_code=status.HTTP_201_CREATED)
def create_match(
    request: MatchRequest,
    documents: StoreDep,
    matches: MatchStoreDep,
    master: MasterDep,
    llm: LLMDep,
    erp: ErpDep,
    graph: GraphDep,
    settings: SettingsDep,
) -> MatchRecord:
    invoice_bytes = documents.read(request.invoice_document_id)
    note_bytes = documents.read(request.delivery_note_document_id)
    if invoice_bytes is None or note_bytes is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    return run_match(
        invoice_bytes,
        note_bytes,
        request.invoice_document_id,
        request.delivery_note_document_id,
        settings=settings,
        matches=matches,
        master=master,
        llm=llm,
        erp=erp,
        graph=graph,
    )


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


class Stats(BaseModel):
    matches: int
    by_status: dict[str, int]
    auto_approval_rate: float | None
    findings_by_type: dict[str, int]
    avg_duration_ms: int | None
    total_input_tokens: int
    total_output_tokens: int
    estimated_cost_usd: float | None


@router.get("/v1/stats")
def stats(matches: MatchStoreDep) -> Stats:
    """Totals over all stored matches: what a team lead would watch."""
    records = matches.all()
    results = [r.result for r in records]
    statuses = Counter(r.status.value for r in records)
    costs = [r.estimated_cost_usd for r in results if r.estimated_cost_usd is not None]
    return Stats(
        matches=len(records),
        by_status=dict(statuses),
        auto_approval_rate=round(statuses["auto_approved"] / len(records), 3) if records else None,
        findings_by_type=dict(Counter(f.type.value for r in results for f in r.findings)),
        avg_duration_ms=round(sum(r.duration_ms for r in results) / len(results))
        if results
        else None,
        total_input_tokens=sum(r.llm_input_tokens for r in results),
        total_output_tokens=sum(r.llm_output_tokens for r in results),
        estimated_cost_usd=round(sum(costs), 6) if costs else None,
    )


# --- Demo: sample documents shipped with the demo image ---------------------------------

_SET_ID = re.compile(r"^SET-\d{4}$")


class DemoSet(BaseModel):
    set_id: str
    invoice_file: str
    delivery_note_file: str


def _demo_files(root: Path, set_id: str) -> tuple[Path, Path] | None:
    """Only names of the form SET-0001 are accepted, so no path outside the folder is reachable."""
    if not _SET_ID.match(set_id):
        return None
    folder = root / set_id
    invoice = next(iter(sorted(folder.glob("invoice.*"))), None)
    note = next(iter(sorted(folder.glob("delivery_note.*"))), None)
    return (invoice, note) if invoice and note else None


@router.get("/v1/demo/sets", tags=["demo"])
def demo_sets(settings: SettingsDep) -> list[DemoSet]:
    """Sample sets available on this server (empty unless demo data is installed)."""
    root = settings.erp_orders_dir
    if not root.is_dir():
        return []
    sets = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        files = _demo_files(root, folder.name)
        if files:
            sets.append(
                DemoSet(
                    set_id=folder.name, invoice_file=files[0].name, delivery_note_file=files[1].name
                )
            )
    return sets


@router.post("/v1/demo/sets/{set_id}/match", status_code=status.HTTP_201_CREATED, tags=["demo"])
def demo_match(
    set_id: str,
    documents: StoreDep,
    matches: MatchStoreDep,
    master: MasterDep,
    llm: LLMDep,
    erp: ErpDep,
    graph: GraphDep,
    settings: SettingsDep,
) -> MatchRecord:
    """Upload a sample set's invoice and delivery note and match them, in one call."""
    files = _demo_files(settings.erp_orders_dir, set_id)
    if files is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no demo set {set_id!r}")
    invoice_bytes, note_bytes = files[0].read_bytes(), files[1].read_bytes()
    invoice_doc = documents.save(f"{set_id}-{files[0].name}", invoice_bytes)
    note_doc = documents.save(f"{set_id}-{files[1].name}", note_bytes)
    return run_match(
        invoice_bytes,
        note_bytes,
        invoice_doc.document_id,
        note_doc.document_id,
        settings=settings,
        matches=matches,
        master=master,
        llm=llm,
        erp=erp,
        graph=graph,
    )
