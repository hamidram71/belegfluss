"""The synthetic world: one buyer, a pool of suppliers and one framework contract per supplier.

Everything is derived from a single seed, so a dataset can be regenerated bit for bit.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from faker import Faker

from belegfluss.domain.identifiers import german_iban, german_vat_id
from belegfluss.domain.models import (
    Address,
    ContractClause,
    FrameworkContract,
    Party,
    PaymentTerms,
    PriceAgreement,
    VolumeDiscount,
)
from belegfluss.domain.money import format_unit_price_de, to_unit_price
from belegfluss.master_data import MasterData, Product, SupplierRecord
from belegfluss.synth.catalog import CATALOG, SUPPLIER_PROFILES, CatalogItem, items_in

CONTRACT_START = date(2026, 1, 1)
CONTRACT_END = date(2027, 12, 31)

BUYER = Party(
    party_id="BUYER-0001",
    name="Hartmann Antriebstechnik GmbH",
    address=Address(street="Industriestraße 12", postal_code="74076", city="Heilbronn"),
    vat_id=german_vat_id("28194736"),
    iban=german_iban("62050000", "4711008150"),
    email="einkauf@hartmann-antriebstechnik.example",
)

_PAYMENT_TERMS_OPTIONS: tuple[PaymentTerms, ...] = (
    PaymentTerms(net_days=30, skonto_percent=Decimal("2"), skonto_days=10),
    PaymentTerms(net_days=30, skonto_percent=Decimal("3"), skonto_days=14),
    PaymentTerms(net_days=45, skonto_percent=Decimal("2"), skonto_days=14),
    PaymentTerms(net_days=60),
    PaymentTerms(net_days=30),
)

CATEGORY_LABELS_DE = {
    "fasteners": "Verbindungselementen",
    "bearings": "Wälzlagern",
    "drive": "Antriebselementen",
    "hydraulics": "Hydraulikkomponenten",
    "pneumatics": "Pneumatikkomponenten",
    "sensors": "Sensorik",
    "electrical": "Elektrokomponenten",
    "consumables": "Betriebsstoffen",
    "safety": "Arbeitsschutzartikeln",
    "materials": "Halbzeugen",
    "literature": "Fachliteratur",
}


@dataclass(frozen=True)
class Supplier:
    party: Party
    categories: tuple[str, ...]
    assortment: tuple[CatalogItem, ...]
    contract: FrameworkContract


@dataclass(frozen=True)
class World:
    buyer: Party
    suppliers: tuple[Supplier, ...]


def _random_digits(rng: random.Random, length: int, first_nonzero: bool = True) -> str:
    first = str(rng.randint(1, 9)) if first_nonzero else str(rng.randint(0, 9))
    return first + "".join(str(rng.randint(0, 9)) for _ in range(length - 1))


def new_iban(rng: random.Random) -> str:
    return german_iban(_random_digits(rng, 8), _random_digits(rng, 10))


_LEGAL_FORMS = ("GmbH", "AG", "KG", "KGaA", "OHG", "GbR", "SE", "UG", "e.K.", "e.G.")


def _company_name(rng: random.Random, fake: Faker) -> str:
    """Faker sometimes returns a bare surname; real suppliers always carry a legal form."""
    name: str = fake.unique.company()
    if not any(form in name.split() or name.endswith(form) for form in _LEGAL_FORMS):
        name += rng.choice([" GmbH", " GmbH & Co. KG", " AG", " KG"])
    return name


_TRANSLIT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def ascii_slug(text: str) -> str:
    """Lower-case ASCII slug, with German umlauts transliterated (Müller -> mueller)."""
    return "".join(ch for ch in text.lower().translate(_TRANSLIT) if ch.isascii() and ch.isalnum())


def _make_party(rng: random.Random, fake: Faker, index: int) -> Party:
    name = _company_name(rng, fake)
    slug = ascii_slug(name)[:18]
    return Party(
        party_id=f"K-{70001 + index}",
        name=name,
        address=Address(
            street=fake.street_address(), postal_code=fake.postcode(), city=fake.city()
        ),
        vat_id=german_vat_id(_random_digits(rng, 8)),
        iban=new_iban(rng),
        email=f"rechnung@{slug}.example",
    )


def _contract_clauses(
    contract_number: str,
    supplier: Party,
    categories: tuple[str, ...],
    agreements: list[PriceAgreement],
    discount: VolumeDiscount | None,
    terms: PaymentTerms,
    wording: random.Random,
) -> tuple[list[ContractClause], dict[str, str]]:
    """Build the clauses. Titles and phrasing vary between contracts (``wording``), as they do
    in real contracts, so that retrieval has to find a clause by meaning, not by fixed words.
    The facts (prices, thresholds, terms) never vary with the wording."""
    goods = ", ".join(CATEGORY_LABELS_DE[c] for c in categories)
    clauses: list[ContractClause] = []

    def add(titles: tuple[str, ...], texts: tuple[str, ...]) -> str:
        clause_id = f"§ {len(clauses) + 1}"
        clauses.append(
            ContractClause(
                clause_id=clause_id, title=wording.choice(titles), text=wording.choice(texts)
            )
        )
        return clause_id

    add(
        ("Vertragsgegenstand", "Gegenstand des Vertrags"),
        (
            f"Dieser Rahmenvertrag ({contract_number}) regelt die Lieferung von {goods} durch die "
            f"{supplier.name} (Lieferant) an die {BUYER.name} (Besteller). Einzelne Lieferungen "
            "erfolgen ausschließlich auf Grundlage schriftlicher Bestellungen des Bestellers.",
        ),
    )
    add(
        ("Laufzeit", "Vertragsdauer"),
        (
            f"Der Vertrag gilt vom {CONTRACT_START:%d.%m.%Y} bis zum {CONTRACT_END:%d.%m.%Y}. "
            "Eine Verlängerung bedarf der Schriftform.",
        ),
    )
    price_id = add(
        ("Preise", "Vergütung", "Preisvereinbarung"),
        (
            "Es gelten die in Anlage 1 vereinbarten Nettopreise je Einheit zuzüglich der "
            "gesetzlichen Umsatzsteuer. Die Preise sind für die gesamte Vertragslaufzeit "
            "Festpreise. Preiserhöhungen, Zuschläge sowie Fracht- und Verpackungspauschalen sind "
            "nur nach vorheriger schriftlicher Vereinbarung zulässig.",
            "Maßgeblich sind die Nettopreise der Preisliste in Anlage 1; sie bleiben während der "
            "Laufzeit unverändert. Zusätzliche Kosten wie Versand, Verpackung oder sonstige "
            "Aufschläge darf der Lieferant nur berechnen, wenn dies vorher schriftlich vereinbart "
            "wurde.",
        ),
    )
    if discount is not None:
        n, pct = discount.min_quantity, discount.percent
        discount_id = add(
            ("Mengenrabatt", "Rabattstaffel", "Preisnachlass bei Großmengen"),
            (
                f"Erreicht die Bestellmenge einer einzelnen Bestellposition mindestens {n} "
                f"Einheiten, gewährt der Lieferant auf den Preis dieser Position einen "
                f"zusätzlichen Rabatt von {pct} %. Der Rabatt ist auf der Rechnung im "
                "Einzelpreis zu berücksichtigen.",
                f"Bei einer Abnahmemenge von {n} Einheiten oder mehr je Bestellposition reduziert "
                f"sich der vereinbarte Einzelpreis dieser Position um {pct} %. Die Reduzierung "
                "ist bereits im Rechnungsbetrag auszuweisen.",
                f"Für Bestellpositionen ab {n} Einheiten gilt ein Nachlass von {pct} % auf den "
                "Preis gemäß Anlage 1, der direkt vom Einzelpreis abzuziehen ist.",
            ),
        )
        discount = discount.model_copy(update={"clause_id": discount_id})
    payment_id = add(
        ("Zahlungsbedingungen", "Zahlung", "Zahlungsziel und Skonto"),
        (
            f"{terms.describe_de()} Die Frist beginnt mit Eingang einer prüffähigen Rechnung. "
            "Abweichende Zahlungsbedingungen auf Rechnungen des Lieferanten sind unwirksam.",
            f"Für alle Rechnungen gilt: {terms.describe_de()} Von diesem Vertrag abweichende "
            "Angaben des Lieferanten zu Zahlungsfristen oder Skonto entfalten keine Wirkung.",
        ),
    )
    delivery_id = add(
        ("Lieferung und Teillieferungen", "Lieferungen", "Liefermengen"),
        (
            "Teillieferungen sind zulässig. Berechnet werden ausschließlich die tatsächlich "
            "gelieferten und durch Lieferschein bestätigten Mengen. Mehrmengen bedürfen der "
            "Zustimmung des Bestellers.",
            "Der Lieferant darf in Teilmengen liefern. In Rechnung gestellt werden darf nur, was "
            "laut unterschriebenem Lieferschein tatsächlich angenommen wurde.",
        ),
    )
    add(
        ("Rechnungsstellung", "Rechnungen"),
        (
            "Rechnungen sind als E-Rechnung im Format XRechnung oder ZUGFeRD (Profil EN 16931) "
            "zu übermitteln. Jede Rechnung muss die Bestellnummer und die Lieferscheinnummer "
            "enthalten.",
        ),
    )
    bank_id = add(
        ("Bankverbindung", "Zahlungsempfänger", "Kontoänderungen"),
        (
            "Zahlungen erfolgen ausschließlich auf das in den Stammdaten des Bestellers "
            "hinterlegte Konto des Lieferanten. Änderungen der Bankverbindung sind schriftlich "
            "mitzuteilen und werden erst nach telefonischer Rückbestätigung durch den Besteller "
            "wirksam.",
            "Der Besteller leistet Zahlungen nur auf die im Lieferantenstamm hinterlegte IBAN. "
            "Mitteilungen über eine neue Bankverbindung, auch per E-Mail oder auf Rechnungen, "
            "sind ohne schriftliche und telefonisch bestätigte Vereinbarung unbeachtlich.",
        ),
    )
    price_lines = "\n".join(
        f"{a.sku} – {a.description}: {format_unit_price_de(a.unit_price)} je {a.unit.label_de}"
        for a in agreements
    )
    clauses.append(
        ContractClause(
            clause_id="Anlage 1",
            title="Preisliste",
            text=f"Vereinbarte Nettopreise (Festpreise gemäß {price_id}):\n{price_lines}",
        )
    )
    ids = {
        "price_list": "Anlage 1",
        "price": price_id,
        "payment": payment_id,
        "delivery": delivery_id,
        "bank": bank_id,
        "discount": discount.clause_id if discount else "",
    }
    return clauses, ids


def _make_contract(
    rng: random.Random, seed: int, index: int, supplier: Party, categories: tuple[str, ...]
) -> tuple[FrameworkContract, tuple[CatalogItem, ...]]:
    assortment = items_in(categories)
    covered = rng.sample(assortment, k=min(len(assortment), rng.randint(5, 8)))
    agreements = [
        PriceAgreement(
            sku=item.sku,
            description=item.description,
            unit=item.unit,
            unit_price=to_unit_price(item.list_price * Decimal(str(rng.uniform(0.82, 0.95)))),
        )
        for item in sorted(covered, key=lambda i: i.sku)
    ]
    discount = (
        VolumeDiscount(
            min_quantity=Decimal(rng.choice([50, 100, 200])),
            percent=Decimal(rng.choice([2, 3, 5])),
            clause_id="pending",
        )
        if rng.random() < 0.5
        else None
    )
    terms = rng.choice(_PAYMENT_TERMS_OPTIONS)
    number = f"RV-2026-{index + 1:03d}"
    wording = random.Random(f"wording-{seed}-{index}")  # separate stream: sets stay identical
    clauses, ids = _contract_clauses(
        number, supplier, categories, agreements, discount, terms, wording
    )
    if discount is not None:
        discount = discount.model_copy(update={"clause_id": ids["discount"]})
    contract = FrameworkContract(
        contract_number=number,
        supplier=supplier,
        buyer=BUYER,
        valid_from=CONTRACT_START,
        valid_to=CONTRACT_END,
        price_agreements=agreements,
        volume_discount=discount,
        payment_terms=terms,
        price_list_clause_id=ids["price_list"],
        payment_terms_clause_id=ids["payment"],
        partial_delivery_clause_id=ids["delivery"],
        bank_details_clause_id=ids["bank"],
        clauses=clauses,
    )
    return contract, tuple(assortment)


def master_data_from_world(world: World) -> MasterData:
    """The buyer's ERP view of the world: what checks are allowed to know."""
    return MasterData(
        buyer=world.buyer,
        suppliers=[
            SupplierRecord(
                party=s.party,
                payment_terms=s.contract.payment_terms,
                contract_number=s.contract.contract_number,
            )
            for s in world.suppliers
        ],
        products=[
            Product(sku=i.sku, description=i.description, unit=i.unit, vat_rate=i.vat_rate)
            for i in CATALOG
        ],
    )


def build_world(seed: int, n_suppliers: int = 12) -> World:
    rng = random.Random(seed)
    fake = Faker("de_DE")
    fake.seed_instance(seed)
    suppliers = []
    for index in range(n_suppliers):
        party = _make_party(rng, fake, index)
        categories = SUPPLIER_PROFILES[index % len(SUPPLIER_PROFILES)]
        contract, assortment = _make_contract(rng, seed, index, party, categories)
        suppliers.append(Supplier(party, categories, assortment, contract))
    return World(buyer=BUYER, suppliers=tuple(suppliers))
