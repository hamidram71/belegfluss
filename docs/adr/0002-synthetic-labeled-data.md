# ADR 0002: Synthetic, labeled data instead of real documents

- Status: accepted
- Date: 2026-10-19

## Context

Real invoices and delivery notes contain personal data (names, contact details, bank
accounts) and confidential prices. Using them in a public repository is not possible under
GDPR and commercial confidentiality, and anonymising them reliably is itself hard.

An AI system also cannot be developed responsibly without labeled data to measure it against.

## Decision

Build a deterministic generator (`belegfluss-synth`) that creates a complete synthetic world
from one seed and labels every case:

- The same Pydantic models are used for generation, extraction and evaluation, so there is a
  single vocabulary for documents and for discrepancies.
- Each set starts as a correct purchase-to-pay case. Discrepancies from a fixed taxonomy are
  then injected into the invoice and recorded with type, line, expected/actual value and the
  contract clause that proves them.
- Clean sets contain **legitimate variations** (partial deliveries, articles without contract
  price, applied volume discounts, supplier-specific wording) so that a system that flags
  everything unusual is penalised.
- Documents are rendered in realistic formats with format-specific difficulty: XRechnung XML,
  ZUGFeRD PDF, plain PDF and scans with skew, noise and blur. Layouts vary per supplier.
- Ground truth is written to a separate folder and never placed next to the input documents.

## Consequences

- Fully reproducible experiments: a seed and a generator version identify a dataset.
- Results on synthetic data overstate real-world accuracy. Real-world validation needs
  consenting design partners; this is part of the product validation plan, not of the repo.
- Generated PDFs are not PDF/A-3 and XRechnung output is not yet checked with the KoSIT
  validator (week 2). Both limitations are documented in the README.
