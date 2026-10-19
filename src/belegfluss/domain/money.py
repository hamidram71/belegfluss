"""Money helpers.

All monetary values are ``Decimal``. Floats are never used for amounts, because binary
floating point cannot represent cent values exactly (see docs/adr/0003).
"""

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
SUB_CENT = Decimal("0.0001")


def to_money(value: Decimal | int | str) -> Decimal:
    """Round a value to whole cents using commercial rounding (ROUND_HALF_UP)."""
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def to_unit_price(value: Decimal | int | str) -> Decimal:
    """Round a unit price. Prices below 1 EUR keep four decimals, as is usual for small parts.

    EN 16931 allows more than two decimals for the item net price (BT-146); only line and
    document totals are rounded to cents.
    """
    amount = Decimal(value)
    return amount.quantize(SUB_CENT if abs(amount) < 1 else CENT, rounding=ROUND_HALF_UP)


def percent_of(amount: Decimal, rate_percent: Decimal) -> Decimal:
    """Return ``rate_percent`` % of ``amount``, rounded to cents."""
    return to_money(amount * rate_percent / Decimal(100))


def format_eur_de(amount: Decimal) -> str:
    """Format an amount the German way, e.g. ``1.234,56 €``."""
    quantized = to_money(amount)
    sign = "-" if quantized < 0 else ""
    integer, _, fraction = f"{abs(quantized):.2f}".partition(".")
    groups: list[str] = []
    while integer:
        groups.insert(0, integer[-3:])
        integer = integer[:-3]
    return f"{sign}{'.'.join(groups)},{fraction} €"


def format_unit_price_de(price: Decimal) -> str:
    """Format a unit price with two or four decimals, e.g. ``0,1552 €`` or ``12,40 €``."""
    if price == to_money(price):
        return format_eur_de(price)
    text = f"{price:.4f}".replace(".", ",")
    return f"{text} €"


def format_decimal_de(value: Decimal) -> str:
    """Format a quantity or rate the German way without trailing zeros, e.g. ``12,5``."""
    text = format(value.normalize(), "f")
    return text.replace(".", ",")
