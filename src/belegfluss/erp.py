"""Purchase orders as exported from the buyer's ERP system."""

from __future__ import annotations

from pathlib import Path

from belegfluss.domain.models import PurchaseOrder


class ErpOrders:
    def __init__(self, orders: dict[str, PurchaseOrder]) -> None:
        self.orders = orders

    @classmethod
    def load(cls, directory: Path) -> ErpOrders:
        orders = {}
        for path in sorted(directory.rglob("purchase_order.json")):
            order = PurchaseOrder.model_validate_json(path.read_text(encoding="utf-8"))
            orders[order.po_number] = order
        return cls(orders)

    def get(self, po_number: str) -> PurchaseOrder | None:
        return self.orders.get(po_number)

    def numbers(self) -> set[str]:
        return set(self.orders)
