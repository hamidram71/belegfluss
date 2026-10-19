from decimal import Decimal as D

from belegfluss.domain.money import (
    format_decimal_de,
    format_eur_de,
    format_unit_price_de,
    to_money,
    to_unit_price,
)


def test_commercial_rounding_half_up() -> None:
    assert to_money(D("2.675")) == D("2.68")  # float would round to 2.67
    assert to_money(D("0.005")) == D("0.01")


def test_unit_prices_below_one_euro_keep_four_decimals() -> None:
    assert to_unit_price(D("0.15555")) == D("0.1556")
    assert to_unit_price(D("12.345")) == D("12.35")


def test_german_formatting() -> None:
    assert format_eur_de(D("1234567.5")) == "1.234.567,50 €"
    assert format_eur_de(D("-3")) == "-3,00 €"
    assert format_unit_price_de(D("0.1552")) == "0,1552 €"
    assert format_unit_price_de(D("12.40")) == "12,40 €"
    assert format_decimal_de(D("12.50")) == "12,5"
    assert format_decimal_de(D("100")) == "100"
