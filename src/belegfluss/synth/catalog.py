"""Product catalog for the synthetic world: typical MRO and production parts of a machine builder.

Prices are invented list prices in EUR (net). A few items carry the reduced VAT rate of 7 %
(printed technical literature) so that wrong VAT rates are a realistic error class.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from belegfluss.domain.models import UnitCode


@dataclass(frozen=True)
class CatalogItem:
    sku: str
    description: str
    unit: UnitCode
    list_price: Decimal
    category: str
    vat_rate: Decimal = Decimal("19")


def _item(
    sku: str, description: str, unit: UnitCode, price: str, category: str, vat: str = "19"
) -> CatalogItem:
    return CatalogItem(sku, description, unit, Decimal(price), category, Decimal(vat))


P, M, K, S = UnitCode.PIECE, UnitCode.METRE, UnitCode.KILOGRAM, UnitCode.SET

CATALOG: tuple[CatalogItem, ...] = (
    # Fasteners
    _item("SCH-M8x40-89", "Sechskantschraube DIN 933 M8x40, 8.8 verzinkt", P, "0.18", "fasteners"),
    _item(
        "SCH-M10x60-89", "Sechskantschraube DIN 933 M10x60, 8.8 verzinkt", P, "0.34", "fasteners"
    ),
    _item("MUT-M8-8", "Sechskantmutter DIN 934 M8, Klasse 8", P, "0.06", "fasteners"),
    _item("MUT-M10-8", "Sechskantmutter DIN 934 M10, Klasse 8", P, "0.09", "fasteners"),
    _item("SCH-ISK-M6x20", "Zylinderschraube ISO 4762 M6x20, 12.9", P, "0.21", "fasteners"),
    _item("SIC-DIN471-25", "Sicherungsring DIN 471, 25 mm", P, "0.12", "fasteners"),
    # Bearings and drive
    _item("KGL-6204-2RS", "Rillenkugellager 6204-2RS, 20x47x14 mm", P, "4.85", "bearings"),
    _item("KGL-6205-2RS", "Rillenkugellager 6205-2RS, 25x52x15 mm", P, "5.60", "bearings"),
    _item("KGL-6306-ZZ", "Rillenkugellager 6306-ZZ, 30x72x19 mm", P, "9.40", "bearings"),
    _item("ZRL-HTD-8M-30", "Zahnriemen HTD 8M, Breite 30 mm, Länge 1200 mm", P, "38.90", "drive"),
    _item("KET-08B-1", "Rollenkette 08B-1, 1/2 Zoll", M, "12.75", "drive"),
    _item("KUP-ROTEX-24", "Elastische Kupplung, Baugröße 24", P, "46.20", "drive"),
    # Hydraulics and pneumatics
    _item("HYD-SCHL-DN10", "Hydraulikschlauch 2SN DN10, 330 bar", M, "8.95", "hydraulics"),
    _item("HYD-VER-DN10", "Pressarmatur DKOL DN10, M18x1,5", P, "6.40", "hydraulics"),
    _item("HYD-OEL-HLP46", "Hydrauliköl HLP 46, Gebinde 20 l", P, "89.00", "hydraulics"),
    _item("PNE-ZYL-32x100", "Pneumatikzylinder ISO 15552, 32x100 mm", P, "74.50", "pneumatics"),
    _item("PNE-VEN-52-G14", "5/2-Wegeventil, G1/4, 24 V DC", P, "58.30", "pneumatics"),
    _item("PNE-SCHL-8", "Pneumatikschlauch PU, 8x6 mm, blau", M, "0.85", "pneumatics"),
    # Electrical and sensors
    _item("SEN-IND-M12", "Induktiver Näherungsschalter M12, PNP, 4 mm", P, "21.90", "sensors"),
    _item("SEN-OPT-RL", "Reflexionslichtschranke, Reichweite 6 m", P, "64.00", "sensors"),
    _item("KAB-OLF-3G15", "Steuerleitung 3G1,5 mm², ölbeständig", M, "1.45", "electrical"),
    _item("KAB-M12-5P-5M", "Sensorleitung M12, 5-polig, 5 m", P, "11.20", "electrical"),
    _item("SCH-LS-C16", "Leitungsschutzschalter C16, 1-polig", P, "7.80", "electrical"),
    _item("REL-24V-2W", "Koppelrelais 24 V DC, 2 Wechsler", P, "9.95", "electrical"),
    # Consumables and safety
    _item("SCHM-LIT-EP2", "Mehrzweckfett Lithium EP2, Kartusche 400 g", P, "6.90", "consumables"),
    _item("SCHL-SCH-125", "Schleifscheibe 125x6 mm, Stahl", P, "2.35", "consumables"),
    _item("HDS-NIT-L", "Nitril-Schutzhandschuhe, Größe L, Packung 100", S, "11.50", "safety"),
    _item("SCH-BRI-KL", "Schutzbrille, klar, EN 166", P, "4.20", "safety"),
    _item("REI-IND-5L", "Industriereiniger, Kanister 5 l", P, "18.60", "consumables"),
    _item("STA-RUND-42", "Rundstahl 42CrMo4, Ø 40 mm", K, "3.15", "materials"),
    _item("ALU-PROF-40x40", "Aluminium-Strebenprofil 40x40, Nut 8", M, "14.80", "materials"),
    # Reduced VAT (printed technical literature)
    _item(
        "BUC-DIN-TB-10",
        "DIN-Taschenbuch 10, Mechanische Verbindungselemente",
        P,
        "98.00",
        "literature",
        "7",
    ),
    _item("BUC-HYD-HB", "Fachbuch Hydraulik-Handbuch, 6. Auflage", P, "64.90", "literature", "7"),
)

CATEGORIES: tuple[str, ...] = tuple(sorted({item.category for item in CATALOG}))

# Supplier archetypes: which categories a supplier sells.
SUPPLIER_PROFILES: tuple[tuple[str, ...], ...] = (
    ("fasteners", "consumables"),
    ("bearings", "drive"),
    ("hydraulics", "pneumatics"),
    ("sensors", "electrical"),
    ("consumables", "safety", "literature"),
    ("materials", "fasteners"),
    ("drive", "pneumatics", "literature"),
    ("electrical", "safety"),
)


def items_in(categories: tuple[str, ...]) -> list[CatalogItem]:
    return [item for item in CATALOG if item.category in categories]


def by_sku(sku: str) -> CatalogItem:
    for item in CATALOG:
        if item.sku == sku:
            return item
    raise KeyError(sku)
