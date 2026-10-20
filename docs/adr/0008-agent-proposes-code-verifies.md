# ADR 0008: The matching agent – a workflow where the model proposes and code verifies

- Status: accepted
- Date: 2026-10-20

## Context

The rules (ADR 0006) find discrepancies but cannot explain *why* a price is too high or cite
the contract. That needs the contract text (ADR 0007) and judgement: is this a raised price or
a volume discount that was not applied, and which clause proves it? An LLM can make that call
on varied wording. It can also be wrong, invent a clause, or "quote" text that does not exist,
and in accounts payable a confident wrong answer leads to wrong payments.

## Decision

1. **A fixed workflow, not an open agent loop.** A LangGraph state graph with known steps:
   rules → plausibility → retrieve evidence → adjudicate → verify → decide. Sets without
   findings skip retrieval and the model entirely. Every path is testable and auditable.
2. **The model proposes, code verifies.** For each finding the adjudicator proposes a category
   (from an allowed set for that finding), a clause id and a verbatim quote. Code accepts the
   proposal only if the clause was among the retrieved evidence, the quote occurs in it, and
   for price findings the numbers agree with the price list. A rejected proposal keeps the
   rules' category, is marked unverified, and always goes to human review.
3. **Two interchangeable adjudicators**: a deterministic baseline (reads the price-list row)
   and the LLM adjudicator. Both run on the same sets in `belegfluss-eval agent`, so the LLM
   is measured against a known reference.
4. **The model receives facts, not documents.** The adjudication prompt contains the finding,
   the allowed categories and the retrieved clauses. Supplier documents are not passed in, and
   identifiers such as IBANs are masked (ADR 0009).
5. **The decision is code.** A set is approved only if there is no finding and no plausibility
   issue. The model can influence explanations and categories, never the approve/review choice.
6. **Plausibility checks** catch signs of extraction errors (unknown or mismatching order
   numbers, inconsistent due dates, duplicates, extraction warnings) and route them to review.
7. **Human review queue.** Every result is stored; reviewers approve or reject with name and
   comment, once.

## Consequences

- The LLM adds value where it is needed (classification and explanation on varied wording)
  and cannot cause an approval on its own.
- Building it exposed three real bugs, each now covered by a regression test: price-list rows
  sharing one clause id broke verification; the evidence order hid the discount clause; and the
  data generator could overwrite one price error with another and leave a stale label.
- On synthetic data the deterministic baseline is already at 100 %. That is an upper bound
  (it reads the generator's own wording); the LLM adjudicator's value has to show on varied
  real contracts, which synthetic data can only approximate.
