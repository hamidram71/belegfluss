"""Vector stores for contract chunks.

Retrieval is *hybrid*: results are always restricted to one contract (the invoice names it),
chunks containing an exact keyword (an article number) rank first, and the rest are ranked by
cosine similarity. Exact codes like "KGL-6204-2RS" are what embeddings handle worst, so they
are matched literally.
"""

from __future__ import annotations

import math
from typing import Any, Protocol

from belegfluss.contracts.chunking import Chunk
from belegfluss.domain.models import Model


class VectorStoreUnavailableError(RuntimeError):
    """The configured database cannot be reached."""


class ScoredChunk(Model):
    chunk: Chunk
    similarity: float
    keyword_hit: bool


class VectorStore(Protocol):
    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None: ...

    def search(
        self, contract_number: str, vector: list[float], k: int, keyword: str | None = None
    ) -> list[ScoredChunk]: ...

    def count(self) -> int: ...


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


class InMemoryVectorStore:
    """For tests and small demos. Same ranking semantics as ``PgVectorStore``."""

    def __init__(self) -> None:
        self._items: dict[str, tuple[Chunk, list[float]]] = {}

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        for chunk, vector in zip(chunks, vectors, strict=True):
            self._items[chunk.chunk_id] = (chunk, vector)

    def search(
        self, contract_number: str, vector: list[float], k: int, keyword: str | None = None
    ) -> list[ScoredChunk]:
        needle = keyword.lower() if keyword else None
        scored = [
            ScoredChunk(
                chunk=chunk,
                similarity=_cosine(vector, stored),
                keyword_hit=bool(needle and needle in chunk.text.lower()),
            )
            for chunk, stored in self._items.values()
            if chunk.contract_number == contract_number
        ]
        # Same order as the SQL: keyword hits, similarity (rounded, pgvector stores float32),
        # then chunk id, so ties are broken identically in both stores.
        scored.sort(key=lambda s: (not s.keyword_hit, -round(s.similarity, 6), s.chunk.chunk_id))
        return scored[:k]

    def count(self) -> int:
        return len(self._items)


class PgVectorStore:
    """PostgreSQL + pgvector. Schema is created on first use."""

    def __init__(self, dsn: str, dimensions: int, table: str = "contract_chunks") -> None:
        import psycopg
        from pgvector.psycopg import register_vector

        if not table.isidentifier():
            raise ValueError("invalid table name")
        self.table = table
        self.dimensions = dimensions
        try:
            # Fail fast: without a timeout an unreachable host blocks for the OS default.
            self.conn: Any = psycopg.connect(dsn, autocommit=True, connect_timeout=5)
        except psycopg.OperationalError as exc:
            raise VectorStoreUnavailableError(
                "Cannot reach PostgreSQL for the contract index (BELEGFLUSS_DATABASE_URL). "
                "Start it with `docker compose up -d postgres`, or remove "
                "BELEGFLUSS_DATABASE_URL from .env to use the in-memory index."
            ) from exc
        self.conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        register_vector(self.conn)
        self.conn.execute(
            f"""CREATE TABLE IF NOT EXISTS {table} (
                chunk_id text PRIMARY KEY,
                contract_number text NOT NULL,
                clause_id text NOT NULL,
                title text NOT NULL,
                text text NOT NULL,
                embedding vector({dimensions}) NOT NULL
            )"""
        )
        self.conn.execute(
            f"CREATE INDEX IF NOT EXISTS {table}_contract_idx ON {table} (contract_number)"
        )
        # Deliberately no HNSW/IVFFlat index: approximate indexes filter *after* the vector
        # search, so a per-contract query can miss rows. One contract has only a few dozen
        # chunks, so an exact scan over the btree-filtered rows is correct and fast (ADR 0007).

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        import numpy as np

        with self.conn.cursor() as cur:
            cur.executemany(
                f"""INSERT INTO {self.table}
                    (chunk_id, contract_number, clause_id, title, text, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (chunk_id) DO UPDATE SET
                      contract_number = EXCLUDED.contract_number,
                      clause_id = EXCLUDED.clause_id, title = EXCLUDED.title,
                      text = EXCLUDED.text, embedding = EXCLUDED.embedding""",
                [
                    (c.chunk_id, c.contract_number, c.clause_id, c.title, c.text, np.array(v))
                    for c, v in zip(chunks, vectors, strict=True)
                ],
            )

    def search(
        self, contract_number: str, vector: list[float], k: int, keyword: str | None = None
    ) -> list[ScoredChunk]:
        import numpy as np

        query = np.array(vector)
        rows = self.conn.execute(
            f"""SELECT chunk_id, contract_number, clause_id, title, text,
                       1 - (embedding <=> %(q)s) AS similarity,
                       (%(kw)s::text IS NOT NULL
                        AND strpos(lower(text), lower(%(kw)s::text)) > 0) AS keyword_hit
                FROM {self.table}
                WHERE contract_number = %(contract)s
                ORDER BY keyword_hit DESC,
                         round((1 - (embedding <=> %(q)s))::numeric, 6) DESC,
                         chunk_id
                LIMIT %(k)s""",
            {"q": query, "kw": keyword, "contract": contract_number, "k": k},
        ).fetchall()
        return [
            ScoredChunk(
                chunk=Chunk(
                    chunk_id=r[0], contract_number=r[1], clause_id=r[2], title=r[3], text=r[4]
                ),
                similarity=float(r[5]),
                keyword_hit=bool(r[6]),
            )
            for r in rows
        ]

    def count(self) -> int:
        row = self.conn.execute(f"SELECT count(*) FROM {self.table}").fetchone()
        return int(row[0])

    def drop(self) -> None:
        self.conn.execute(f"DROP TABLE IF EXISTS {self.table}")
