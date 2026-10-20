"""Lenient parsers for values as they appear on German documents and in LLM output."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from belegfluss.domain.models import PaymentTerms, UnitCode


class ValueParseError(ValueError):
    pass


_THOUSANDS_DOT = re.compile(r"^-?\d{1,3}(\.\d{3})+$")


def parse_decimal(text: str | int | float | Decimal) -> Decimal:
    """Parse ``1.234,56``, ``1234.56``, ``0,2844``, ``19 %`` or ``12,40 €`` into a Decimal.

    Rules: if both separators occur, the last one is the decimal separator. A lone comma is a
    decimal comma. A lone dot is a decimal point, unless the number looks like German
    thousands grouping (``1.234`` or ``12.345.678``).
    """
    if isinstance(text, Decimal):
        return text
    if isinstance(text, int):
        return Decimal(text)
    if isinstance(text, float):
        return Decimal(str(text))
    cleaned = re.sub(r"[€%\s]|EUR", "", text.strip())
    cleaned = cleaned.replace("\u2212", "-")
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    elif _THOUSANDS_DOT.match(cleaned):
        cleaned = cleaned.replace(".", "")
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueParseError(f"not a number: {text!r}") from exc


def parse_date(text: str) -> date:
    """Parse ``2026-04-02``, ``02.04.2026`` or ``20260402`` (CII format 102)."""
    value = text.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y%m%d", "%d.%m.%y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueParseError(f"not a date: {text!r}")


_NET = re.compile(r"(\d+)\s*Tage[n]?\s*netto", re.IGNORECASE)
_SKONTO = re.compile(r"(\d+)\s*Tage[n]?\s*(\d+(?:[.,]\d+)?)\s*%\s*Skonto", re.IGNORECASE)
_XR_SKONTO = re.compile(r"#SKONTO#TAGE=(\d+)#PROZENT=(\d+(?:\.\d+)?)#")


def parse_payment_terms(text: str, fallback_net_days: int | None = None) -> PaymentTerms:
    """Parse German payment terms text, including the XRechnung ``#SKONTO#`` notation."""
    net = _NET.search(text)
    net_days = int(net.group(1)) if net else fallback_net_days
    if net_days is None:
        raise ValueParseError(f"no net payment period in {text!r}")
    skonto = _SKONTO.search(text) or _XR_SKONTO.search(text)
    if skonto:
        return PaymentTerms(
            net_days=net_days,
            skonto_days=int(skonto.group(1)),
            skonto_percent=parse_decimal(skonto.group(2)).normalize(),
        )
    return PaymentTerms(net_days=net_days)


_UNIT_LABELS = {
    "stk": UnitCode.PIECE,
    "stück": UnitCode.PIECE,
    "st": UnitCode.PIECE,
    "pce": UnitCode.PIECE,
    "satz": UnitCode.SET,
    "set": UnitCode.SET,
    "m": UnitCode.METRE,
    "meter": UnitCode.METRE,
    "kg": UnitCode.KILOGRAM,
    "l": UnitCode.LITRE,
    "liter": UnitCode.LITRE,
}


def parse_unit(text: str | None) -> UnitCode:
    """Map a printed unit (``Stk``, ``m``) or a UN/ECE code (``H87``) to a UnitCode."""
    if not text:
        raise ValueParseError("missing unit")
    value = text.strip()
    try:
        return UnitCode(value.upper())
    except ValueError:
        pass
    unit = _UNIT_LABELS.get(value.casefold().rstrip("."))
    if unit is None:
        raise ValueParseError(f"unknown unit: {text!r}")
    return unit
