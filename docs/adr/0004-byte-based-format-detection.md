# ADR 0004: Trust bytes, not file names, on intake

- Status: accepted
- Date: 2026-10-19

## Context

Uploads arrive with a file name and a client-supplied content type. Both are controlled by the
sender and can be wrong by accident ("rechnung.xml" that is a PDF) or on purpose. Downstream
processing (XML parser vs. OCR vs. LLM) depends on the format, so a wrong classification can
route content into the wrong parser.

## Decision

- The format is determined from the file content only: PDF magic bytes, PNG/JPEG signatures,
  and the root element of XML (CII `CrossIndustryInvoice` or UBL `Invoice-2`).
- PDFs are additionally checked for embedded e-invoice attachments (`factur-x.xml`,
  `zugferd-invoice.xml`, `xrechnung.xml`) to recognise hybrid ZUGFeRD invoices.
- Anything else is rejected with HTTP 415. Uploads have a size limit (HTTP 413).
- Stored files get a server-generated UUID; the original file name is kept only as metadata
  and never used as a path. Document lookups validate the UUID before touching the disk.
- A SHA-256 hash is stored for duplicate detection and audit.

## Consequences

- Misnamed files are handled correctly; path traversal through file names or IDs is not
  possible.
- This is the first layer of treating documents as untrusted input. Content-level defences
  against prompt injection follow in week 5.
