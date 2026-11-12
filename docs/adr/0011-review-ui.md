# ADR 0011: A small review UI, served by the API

- Status: accepted
- Date: 2026-11-12

## Context

Reviewers in accounts payable need to see at a glance whether an invoice can be paid and why
not, and then decide. Swagger (`/docs`) proves the API works, but it is not a tool a clerk would
use, and it makes a poor demo. The UI shows text that originates in supplier documents
(article descriptions, names), which are untrusted input (ADR 0009).

## Decision

- **One static page in TypeScript, served by FastAPI at `/ui`** (the root redirects there).
  No framework: three views (inbox, document, decision) do not justify a build pipeline of
  React or Vue. TypeScript runs in strict mode; every API response has a type.
- **German wording for German users**, written from their side: "Abweichungen", "Freigeben",
  "Ablehnen", sentence case, errors that say what to do.
- **Text only, never HTML from data.** Every value is inserted with `textContent`; a test fails
  if `innerHTML`, `outerHTML`, `insertAdjacentHTML` or `document.write` appear in the code.
- **The compiled `app.js` is committed**, so installing the Python package needs no Node.js.
  CI rebuilds it from source with `npm ci` and fails if the committed file differs.
- **Visual language from the domain**: copy paper, ballpoint-ink text, ledger rules, an
  inspection stamp for the decision (the one loud element) and a highlighter on the contract
  sentence that proves a finding. System fonts only, so the page loads nothing external.
- **One-click demo**: `/v1/demo/sets` lists the sample sets shipped in the demo image, and
  `/v1/demo/sets/{set_id}/match` uploads and matches one in a single call. Set ids are checked
  against `SET-` plus four digits, so no other file on the server is reachable.

## Consequences

- A reviewer can work the queue without knowing the API; the demo needs no file juggling.
- Reviewing the UI in a real browser found a content bug the evaluation could not: the
  rule-based adjudicator quoted the first sentence of a clause ("Teillieferungen sind
  zulässig"), which argues for the supplier. It now quotes the sentence that carries the
  evidence, covered by a regression test.
- There is no authentication: the reviewer name is typed in, as in a demo. A production
  deployment would sit behind the company's identity provider (Entra ID with Container Apps
  authentication) and take the name from the token.
