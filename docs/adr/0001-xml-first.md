# ADR 0001: XML first, LLM only for unstructured documents

- Status: accepted
- Date: 2026-10-19

## Context

German B2B e-invoicing is becoming mandatory. Receiving EN 16931 e-invoices (XRechnung,
ZUGFeRD) is required since 1 January 2025; issuing them is required from 1 January 2027 for
companies with more than EUR 800,000 turnover in the previous year and from 1 January 2028
for all others. A growing share of invoices will therefore arrive as structured XML, either
pure or embedded in a PDF.

Delivery notes, order confirmations and contracts are not covered by this obligation and will
keep arriving as PDFs and scans.

## Decision

1. Intake detects the format from the file's bytes (ADR 0004).
2. If structured data exists (CII or UBL XML, or XML embedded in a hybrid PDF), it is parsed
   deterministically and validated against EN 16931. **No LLM call is made** for that document.
3. Only documents without structured data go to OCR and LLM-based structured extraction, with
   output constrained to the same Pydantic models.
4. For hybrid PDFs the embedded XML is authoritative; the visual part is only used for display.

## Consequences

- Lower cost and latency, and exact values (no OCR or model errors) for most invoices.
- The LLM budget is spent where it adds value: delivery notes, legacy PDFs and contracts.
- Two extraction paths must produce identical models; tests compare both against ground truth.
- The share of LLM-processed invoices will fall over time, so evaluation reports results per
  input format rather than one blended number.
