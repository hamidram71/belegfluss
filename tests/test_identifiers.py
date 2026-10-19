import pytest

from belegfluss.domain.identifiers import (
    format_iban,
    german_iban,
    german_vat_id,
    is_valid_german_vat_id,
    is_valid_iban,
)


def test_known_reference_iban_is_valid() -> None:
    assert is_valid_iban("DE89 3704 0044 0532 0130 00")
    assert german_iban("37040044", "532013000") == "DE89370400440532013000"


@pytest.mark.parametrize(
    "iban",
    ["DE89370400440532013001", "DE8937040044053201300", "XX89370400440532013000", ""],
)
def test_invalid_ibans_are_rejected(iban: str) -> None:
    assert not is_valid_iban(iban)


def test_format_iban_groups_by_four() -> None:
    assert format_iban("DE89370400440532013000") == "DE89 3704 0044 0532 0130 00"


def test_known_reference_vat_id_is_valid() -> None:
    assert is_valid_german_vat_id("DE136695976")
    assert german_vat_id("13669597") == "DE136695976"


@pytest.mark.parametrize("vat_id", ["DE136695977", "DE036695976", "DE13669597", "AT136695976"])
def test_invalid_vat_ids_are_rejected(vat_id: str) -> None:
    assert not is_valid_german_vat_id(vat_id)


def test_vat_id_must_not_start_with_zero() -> None:
    with pytest.raises(ValueError):
        german_vat_id("03669597")
