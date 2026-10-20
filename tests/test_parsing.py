from datetime import date
from decimal import Decimal as D

import pytest

from belegfluss.domain.models import PaymentTerms, UnitCode
from belegfluss.extraction.parsing import (
    ValueParseError,
    parse_date,
    parse_decimal,
    parse_payment_terms,
    parse_unit,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1.234,56", D("1234.56")),
        ("1234.56", D("1234.56")),
        ("0,2844", D("0.2844")),
        ("12,40 €", D("12.40")),
        ("19 %", D("19")),
        ("1.000", D("1000")),
        ("1,234.56", D("1234.56")),
        ("12.345.678", D("12345678")),
        ("2.5", D("2.5")),
        ("−3,50", D("-3.50")),
        ("1 234,56 EUR", D("1234.56")),
    ],
)
def test_parse_decimal(text: str, expected: D) -> None:
    assert parse_decimal(text) == expected


def test_parse_decimal_rejects_garbage() -> None:
    with pytest.raises(ValueParseError):
        parse_decimal("zwölf")


@pytest.mark.parametrize("text", ["2026-04-02", "02.04.2026", "20260402"])
def test_parse_date(text: str) -> None:
    assert parse_date(text) == date(2026, 4, 2)


def test_payment_terms_german_text_and_xrechnung_notation() -> None:
    expected = PaymentTerms(net_days=30, skonto_percent=D("2"), skonto_days=10)
    assert parse_payment_terms(expected.describe_de()) == expected
    assert (
        parse_payment_terms("Zahlbar innerhalb 30 Tagen netto. #SKONTO#TAGE=10#PROZENT=2.00#")
        == expected
    )
    assert parse_payment_terms("Zahlbar innerhalb von 60 Tagen netto.") == PaymentTerms(net_days=60)
    assert parse_payment_terms("sofort fällig", fallback_net_days=14) == PaymentTerms(net_days=14)
    with pytest.raises(ValueParseError):
        parse_payment_terms("sofort fällig")


@pytest.mark.parametrize(
    ("text", "unit"),
    [
        ("Stk", UnitCode.PIECE),
        ("Stk.", UnitCode.PIECE),
        ("H87", UnitCode.PIECE),
        ("m", UnitCode.METRE),
        ("Satz", UnitCode.SET),
        ("kg", UnitCode.KILOGRAM),
    ],
)
def test_parse_unit(text: str, unit: UnitCode) -> None:
    assert parse_unit(text) is unit
