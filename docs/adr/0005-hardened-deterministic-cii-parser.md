# ADR 0005: A hardened, explicit parser for CII e-invoices

- Status: accepted
- Date: 2026-10-19

## Context

ADR 0001 sends every structured e-invoice (XRechnung in CII syntax, or the XML embedded in a
ZUGFeRD PDF) to a deterministic parser. That parser processes XML sent by external parties,
so it is an attack surface: classic XML attacks are external entities (XXE, reading local
files or calling internal URLs) and entity expansion ("billion laughs", memory exhaustion).

A generic object mapper would also hide *which* field of the standard a value comes from,
which makes errors hard to trace.

## Decision

- Parse with `lxml` and an explicitly hardened parser: entity resolution off, network access
  off, no DTD loading, no huge trees.
- Read every value with an explicit XPath and name its EN 16931 business term (BT-…) in the
  code, so each field can be traced to the standard.
- Map directly to the same domain models the LLM path produces (`Invoice`), including the
  stated totals as printed (ADR 0003).
- For ZUGFeRD / Factur-X PDFs, extract the embedded XML attachment and treat it as
  authoritative; the visual PDF is not read.
- Missing mandatory elements raise `EInvoiceParseError` with the missing field; nothing is
  guessed.

## Consequences

- Structured invoices are extracted exactly and without model cost. On the synthetic
  dataset, all XRechnung and ZUGFeRD invoices are extracted with 100 % field accuracy.
- UBL syntax is recognised on intake but not parsed yet. XRechnung business rules (KoSIT
  Schematron) are not validated yet; both are listed as known limitations.
