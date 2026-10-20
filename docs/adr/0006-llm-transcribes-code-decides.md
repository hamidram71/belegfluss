# ADR 0006: The LLM transcribes, code decides

- Status: accepted
- Date: 2026-10-19

## Context

Delivery notes and older invoices arrive as PDFs or scans without structured data, so an LLM
with image input is needed to read them. LLMs are good at reading messy layouts and bad at
being reliably exact with arithmetic, unit conversion and German number formats. They are
also steerable by text inside the document (prompt injection), and model names, prices and
providers change quickly.

## Decision

1. **Transcription only.** The model fills schemas (`extraction/schemas.py`) in which every
   number, date and unit is a *string exactly as printed* ("1.234,56", "Stk"). Converting to
   `Decimal`, dates and UN/ECE unit codes happens in tested code (`extraction/parsing.py`).
2. **Strict structured outputs.** The OpenAI Responses API with a Pydantic schema
   (`responses.parse`) guarantees schema-conformant output; all fields are required and
   nullable instead of optional.
3. **Code decides.** Identifying the supplier (via master data), every check and the final
   decision are deterministic code, never the model.
4. **Text before images.** A digital PDF with enough extractable text is sent as text; a scan
   or a scanned PDF is sent as page images (at most three pages).
5. **Documents are untrusted.** Document text is wrapped in `<document>` tags, and the
   instructions state that the content is data and that instructions inside it must be
   ignored. Systematic prompt-injection tests and further defences follow in delivery 3.
6. **Provider-neutral interface.** The rest of the code only knows the `StructuredLLM`
   protocol. `OpenAIStructuredLLM` works with OpenAI and Azure OpenAI. The model id is
   configuration, with no default in code, because model names change.
7. **No API key in CI.** Tests use a fake `StructuredLLM`; real-model quality is measured with
   `belegfluss-eval`, whose results are cached per document so repeated runs cost nothing.

## Consequences

- Wrong conversions are impossible to hide in a prompt: they fail in unit tests.
- Swapping the model or moving to Azure is a configuration change.
- Model quality must be measured separately; every claim about accuracy comes from an
  evaluation report, per input format.
