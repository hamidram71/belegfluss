# ADR 0003: Decimal money, and stated vs. computed totals

- Status: accepted
- Date: 2026-10-19

## Context

Binary floating point cannot represent most cent values exactly (`0.1 + 0.2 != 0.3`), and
Python's `round()` uses banker's rounding (`round(2.675, 2) == 2.67`). Commercial practice in
Germany rounds half up. In an invoice check, a one-cent difference is a real finding.

Invoices can also be internally inconsistent: the printed gross amount does not have to equal
the sum of the lines. A model that derives its totals from the lines can never represent such
an invoice.

## Decision

- All amounts are `decimal.Decimal`. Line and document totals are rounded to cents with
  `ROUND_HALF_UP`.
- Unit prices below 1 EUR keep four decimals, as is common for small parts. EN 16931 allows
  this for the item net price (BT-146); only line and document totals are rounded to cents.
- VAT is calculated per rate on the summed net amounts per rate (EN 16931 VAT breakdown),
  not per line.
- `Invoice.stated_totals` stores the totals **as printed**. `Invoice.computed_totals()` derives
  them from the lines. Validation compares the two instead of trusting either.
- Line net amounts are a derived property and are not serialised, so they cannot drift from
  quantity and price.

## Consequences

- No float anywhere in amounts; JSON carries amounts as strings.
- Inconsistent invoices are representable and testable (`totals_inconsistent`).
