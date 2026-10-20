# ADR 0007: Contract retrieval – clause chunks, fixed queries, exact search

- Status: accepted
- Date: 2026-10-20

## Context

The rules (ADR 0006) detect *that* an invoice price is above the order price, but not *why*:
"price above contract" and "volume discount not applied" look the same in the numbers. The
evidence is in the framework contract. Reviewers also need the clause that justifies a
finding, so the system must find and cite it.

## Decision

1. **Chunk by clause.** One chunk per clause (`§ 4`), one per price-list row (`Anlage 1`,
   one article). Each chunk carries a citable `clause_id`. Headings are detected as short
   lines `§ <n> <Title>`; price rows are anchored on their price line, so wrapped
   descriptions do not break parsing.
2. **Filter first.** The invoice names its contract, so every search is restricted to one
   contract. Retrieval never mixes contracts.
3. **Hybrid ranking.** Chunks that contain an exact keyword (the article number) rank first;
   the rest are ordered by cosine similarity. Embeddings handle codes like `KGL-6204-2RS`
   poorly, so they are matched literally.
4. **Fixed query templates per finding type**, not free-text queries written by a model.
   Retrieval is then reproducible and measurable per type. A price finding retrieves both the
   price row and the volume-discount clause; deciding between them is the agent's job.
5. **Exact search, no approximate index.** pgvector's HNSW/IVFFlat indexes filter *after*
   the approximate search, which can drop rows of the requested contract. A contract has a
   few dozen chunks, so an exact scan over the btree-filtered rows is correct and fast.
   Revisit only if a single contract grows to many thousands of chunks.
6. **Deterministic tie-breaking** (rounded similarity, then chunk id) in both stores, so the
   in-memory store used in tests ranks exactly like PostgreSQL. An integration test runs
   against real pgvector in CI.
7. **Two embedders.** `text-embedding-3-small` (512 dimensions) for real use; an offline
   hashing embedder as a lexical baseline for tests and CI, clearly labelled in reports.
8. **Varied contract wording in the synthetic data.** Titles and phrasing differ between
   contracts ("Mengenrabatt", "Rabattstaffel", "Preisnachlass bei Großmengen"), so retrieval
   has to work by meaning. The facts never vary with the wording.

## Consequences

- On 200 synthetic sets, with the offline baseline embedder, the labelled clause is among the
  candidates for 100 % of findings of every type, and ranked first for every type except the
  volume discount, where the price row ranks first by design.
- These numbers are optimistic: synthetic contracts are short and use a limited set of
  phrasings. Real contracts need measurement with real documents.
- Found while building this: approximate-index filtering and tie ordering both made pgvector
  and the in-memory store disagree. The parity test now guards against both.
