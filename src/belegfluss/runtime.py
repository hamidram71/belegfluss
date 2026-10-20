"""Build the configured components (embedder, contract index, adjudicator, workflow).

One place for wiring, used by the API, the CLIs and the MCP server, so that all of them run
exactly the same configuration.
"""

from __future__ import annotations

import re
from typing import Any

from belegfluss.agent.adjudicator import Adjudicator, DeterministicAdjudicator, LLMAdjudicator
from belegfluss.agent.graph import build_match_graph
from belegfluss.config import Settings
from belegfluss.contracts.embeddings import Embedder, HashingEmbedder, OpenAIEmbedder
from belegfluss.contracts.retrieval import ContractRetriever
from belegfluss.contracts.store import InMemoryVectorStore, PgVectorStore, VectorStore
from belegfluss.extraction.llm import (
    LLMNotConfiguredError,
    StructuredLLM,
    create_llm,
    create_openai_client,
)
from belegfluss.master_data import MasterData


def create_embedder(settings: Settings) -> Embedder:
    if settings.embedding_model:
        return OpenAIEmbedder(
            create_openai_client(settings), settings.embedding_model, settings.embedding_dimensions
        )
    return HashingEmbedder(settings.embedding_dimensions)


def create_vector_store(settings: Settings, embedder: Embedder) -> VectorStore:
    if settings.database_url:
        # One table per embedder: vectors of different models must never be compared.
        table = "contract_chunks_" + re.sub(r"[^a-z0-9]+", "_", embedder.name.lower())
        return PgVectorStore(settings.database_url, embedder.dimensions, table)
    return InMemoryVectorStore()


def create_retriever(settings: Settings, index_if_empty: bool = True) -> ContractRetriever:
    embedder = create_embedder(settings)
    retriever = ContractRetriever(create_vector_store(settings, embedder), embedder)
    if index_if_empty and retriever.store.count() == 0 and settings.contracts_dir.is_dir():
        retriever.index_directory(settings.contracts_dir)
    return retriever


def optional_llm(settings: Settings) -> StructuredLLM | None:
    try:
        return create_llm(settings)
    except LLMNotConfiguredError:
        return None


def create_adjudicator(settings: Settings, llm: StructuredLLM | None) -> Adjudicator:
    if settings.adjudicator == "deterministic" or (settings.adjudicator == "auto" and not llm):
        return DeterministicAdjudicator()
    if llm is None:
        raise LLMNotConfiguredError("BELEGFLUSS_ADJUDICATOR=llm needs a configured LLM")
    return LLMAdjudicator(llm)


def create_match_graph(
    settings: Settings, master: MasterData, llm: StructuredLLM | None
) -> tuple[Any, ContractRetriever]:
    retriever = create_retriever(settings)
    return build_match_graph(master, retriever, create_adjudicator(settings, llm)), retriever
