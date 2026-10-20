"""Buyer-side ERP master data: the reference the checks compare documents against.

Suppliers carry what an ERP vendor record stores (bank account, payment terms, framework
contract). Products carry the VAT rate. Documents are never trusted to provide these values.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path

from belegfluss.domain.models import Model, Party, PaymentTerms, UnitCode


class Product(Model):
    sku: str
    description: str
    unit: UnitCode
    vat_rate: Decimal


class SupplierRecord(Model):
    party: Party
    payment_terms: PaymentTerms
    contract_number: str | None


def _normalise_name(name: str) -> str:
    return re.sub(r"[^a-z0-9äöüß]+", " ", name.casefold()).strip()


def _normalise_vat(vat_id: str) -> str:
    return vat_id.replace(" ", "").upper()


class MasterData(Model):
    buyer: Party
    suppliers: list[SupplierRecord]
    products: list[Product]

    @classmethod
    def load(cls, directory: Path) -> MasterData:
        def read(name: str) -> object:
            return json.loads((directory / name).read_text(encoding="utf-8"))

        return cls.model_validate(
            {
                "buyer": read("buyer.json"),
                "suppliers": read("suppliers.json"),
                "products": read("products.json"),
            }
        )

    def product(self, sku: str | None) -> Product | None:
        return next((p for p in self.products if p.sku == sku), None) if sku else None

    def supplier(self, party_id: str) -> SupplierRecord | None:
        return next((s for s in self.suppliers if s.party.party_id == party_id), None)

    def resolve_supplier(self, vat_id: str | None, name: str | None) -> SupplierRecord | None:
        """Identify a supplier by VAT ID first, then by normalised name. Never by IBAN:
        the IBAN on an invoice is exactly what may have been tampered with."""
        if vat_id:
            wanted = _normalise_vat(vat_id)
            for record in self.suppliers:
                if record.party.vat_id and _normalise_vat(record.party.vat_id) == wanted:
                    return record
        if name:
            wanted = _normalise_name(name)
            for record in self.suppliers:
                if _normalise_name(record.party.name) == wanted:
                    return record
        return None

    def is_buyer(self, vat_id: str | None, name: str | None) -> bool:
        if vat_id and self.buyer.vat_id:
            return _normalise_vat(vat_id) == _normalise_vat(self.buyer.vat_id)
        return bool(name) and _normalise_name(name or "") == _normalise_name(self.buyer.name)
