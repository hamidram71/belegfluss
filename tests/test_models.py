from decimal import Decimal as D

import pytest
from pydantic import ValidationError

from belegfluss.domain.models import LineItem, UnitCode
from belegfluss.synth.world import World


def _line(position: int, qty: str, price: str, vat: str) -> LineItem:
    return LineItem(
        position=position,
        sku=f"SKU-{position}",
        description="x",
        quantity=D(qty),
        unit=UnitCode.PIECE,
        unit_price=D(price),
        vat_rate=D(vat),
    )


def test_line_net_amount_is_rounded_to_cents() -> None:
    assert _line(1, "3", "0.1555", "19").net_amount == D("0.47")


def test_invoice_vat_is_computed_per_rate(world: World) -> None:
    import random

    from belegfluss.synth.scenarios import generate_set

    generated = generate_set(random.Random(1), world, 1, p_discrepant=0.0)
    invoice = generated.invoice.model_copy(
        update={
            "items": [
                _line(1, "10", "10.00", "19"),
                _line(2, "1", "64.90", "7"),
            ]
        }
    )
    breakdown = {line.rate: line for line in invoice.vat_breakdown()}
    assert breakdown[D("19")].amount == D("19.00")
    assert breakdown[D("7")].amount == D("4.54")
    totals = invoice.computed_totals()
    assert (totals.net, totals.vat, totals.gross) == (D("164.90"), D("23.54"), D("188.44"))


def test_contract_volume_discount(world: World) -> None:
    contract = next(s.contract for s in world.suppliers if s.contract.volume_discount)
    discount = contract.volume_discount
    assert discount is not None
    agreement = contract.price_agreements[0]
    below = discount.min_quantity - 1
    assert contract.agreed_unit_price(agreement.sku, below) == agreement.unit_price
    discounted = contract.agreed_unit_price(agreement.sku, discount.min_quantity)
    assert discounted is not None and discounted < agreement.unit_price
    assert contract.agreed_unit_price("UNKNOWN", D(1)) is None


def test_models_are_immutable_and_strict() -> None:
    line = _line(1, "1", "1", "19")
    with pytest.raises(ValidationError):
        line.quantity = D(2)  # type: ignore[misc]
    with pytest.raises(ValidationError):
        LineItem(
            position=0,
            sku="a",
            description="b",
            quantity=D(1),
            unit=UnitCode.PIECE,
            unit_price=D(1),
        )
