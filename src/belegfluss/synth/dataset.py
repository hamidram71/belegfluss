"""Write a complete synthetic dataset to disk.

Layout::

    <out>/
      manifest.json
      master_data/buyer.json, suppliers.json,     # buyer's ERP master data: bank accounts,
                  products.json                   # payment terms, contracts, VAT rates
      contracts/RV-2026-001.pdf ...               # framework contracts (input for RAG)
      sets/SET-0001/purchase_order.json           # ERP export
                    delivery_note.pdf | .png      # digital or scanned
                    invoice.xml | .pdf | .png     # XRechnung, ZUGFeRD, PDF or scan
      ground_truth/contracts/*.json, sets/*.json  # labels, kept outside the input folders
"""

from __future__ import annotations

import json
import random
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from belegfluss import __version__
from belegfluss.domain.documents import DocumentFormat, DocumentKind
from belegfluss.synth.attacks import Attack, make_attack
from belegfluss.synth.ground_truth import DocumentRef, GroundTruthSet, Manifest
from belegfluss.synth.render_pdf import (
    render_contract_pdf,
    render_delivery_note_pdf,
    render_invoice_pdf,
)
from belegfluss.synth.render_xml import render_invoice_xml, render_zugferd_pdf
from belegfluss.synth.scan import pdf_to_scan_png
from belegfluss.synth.scenarios import GeneratedSet, generate_set
from belegfluss.synth.world import build_world, master_data_from_world

INVOICE_FORMATS: dict[DocumentFormat, float] = {
    DocumentFormat.XRECHNUNG_CII: 0.45,
    DocumentFormat.ZUGFERD_PDF: 0.20,
    DocumentFormat.PDF: 0.25,
    DocumentFormat.SCAN: 0.10,
}
DELIVERY_NOTE_FORMATS: dict[DocumentFormat, float] = {
    DocumentFormat.PDF: 0.6,
    DocumentFormat.SCAN: 0.4,
}
_EXTENSIONS = {
    DocumentFormat.XRECHNUNG_CII: ".xml",
    DocumentFormat.ZUGFERD_PDF: ".pdf",
    DocumentFormat.PDF: ".pdf",
    DocumentFormat.SCAN: ".png",
    DocumentFormat.ERP_JSON: ".json",
}


def _pick(rng: random.Random, weights: dict[DocumentFormat, float]) -> DocumentFormat:
    return rng.choices(list(weights), weights=list(weights.values()), k=1)[0]


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _planted(attack: Attack | None, kind: DocumentKind) -> tuple[str | None, bool]:
    if attack is None or attack.document is not kind:
        return None, True
    return attack.text, attack.technique == "hidden_text"


def _render_invoice(
    generated: GeneratedSet, fmt: DocumentFormat, rng: random.Random, attack: Attack | None
) -> bytes:
    if fmt is DocumentFormat.XRECHNUNG_CII:
        return render_invoice_xml(generated.invoice)
    pdf = render_invoice_pdf(generated.invoice, *_planted(attack, DocumentKind.INVOICE))
    if fmt is DocumentFormat.ZUGFERD_PDF:
        return render_zugferd_pdf(generated.invoice, pdf)
    if fmt is DocumentFormat.SCAN:
        return pdf_to_scan_png(pdf, rng)
    return pdf


def _render_delivery(
    generated: GeneratedSet, fmt: DocumentFormat, rng: random.Random, attack: Attack | None
) -> bytes:
    pdf = render_delivery_note_pdf(
        generated.delivery_note, *_planted(attack, DocumentKind.DELIVERY_NOTE)
    )
    return pdf_to_scan_png(pdf, rng) if fmt is DocumentFormat.SCAN else pdf


def write_dataset(
    out_dir: Path,
    n_sets: int = 200,
    seed: int = 42,
    p_discrepant: float = 0.45,
    n_suppliers: int = 12,
    progress: Callable[[int, int], None] | None = None,
    adversarial: float = 0.0,
) -> Manifest:
    """``adversarial`` is the share of sets with a planted prompt-injection attack. Attacks use
    their own random stream, so with ``adversarial=0`` the dataset is unchanged."""
    world = build_world(seed, n_suppliers)
    attack_rng = random.Random(seed + 1000)
    attack_counts: Counter[str] = Counter()
    rng = random.Random(seed + 1)

    _write_json(out_dir / "master_data" / "buyer.json", world.buyer.model_dump(mode="json"))
    master = master_data_from_world(world)
    _write_json(
        out_dir / "master_data" / "suppliers.json",
        [s.model_dump(mode="json") for s in master.suppliers],
    )
    _write_json(
        out_dir / "master_data" / "products.json",
        [p.model_dump(mode="json") for p in master.products],
    )
    for supplier in world.suppliers:
        contract = supplier.contract
        path = out_dir / "contracts" / f"{contract.contract_number}.pdf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(render_contract_pdf(contract))
        _write_json(
            out_dir / "ground_truth" / "contracts" / f"{contract.contract_number}.json",
            contract.model_dump(mode="json"),
        )

    counters: dict[str, Counter[str]] = {
        k: Counter() for k in ("decision", "discrepancy", "invoice", "delivery", "variation")
    }
    for index in range(1, n_sets + 1):
        generated = generate_set(rng, world, index, p_discrepant=p_discrepant)
        set_dir = out_dir / "sets" / generated.set_id
        invoice_fmt = _pick(rng, INVOICE_FORMATS)
        delivery_fmt = _pick(rng, DELIVERY_NOTE_FORMATS)
        attack = (
            make_attack(attack_rng, invoice_fmt, delivery_fmt)
            if adversarial > 0 and attack_rng.random() < adversarial
            else None
        )
        if attack:
            attack_counts[f"{attack.goal}/{attack.technique}"] += 1

        refs = [
            DocumentRef(
                kind=DocumentKind.PURCHASE_ORDER,
                format=DocumentFormat.ERP_JSON,
                path=f"sets/{generated.set_id}/purchase_order.json",
            ),
            DocumentRef(
                kind=DocumentKind.DELIVERY_NOTE,
                format=delivery_fmt,
                path=f"sets/{generated.set_id}/delivery_note{_EXTENSIONS[delivery_fmt]}",
            ),
            DocumentRef(
                kind=DocumentKind.INVOICE,
                format=invoice_fmt,
                path=f"sets/{generated.set_id}/invoice{_EXTENSIONS[invoice_fmt]}",
            ),
        ]
        _write_json(
            set_dir / "purchase_order.json", generated.purchase_order.model_dump(mode="json")
        )
        (out_dir / refs[1].path).write_bytes(_render_delivery(generated, delivery_fmt, rng, attack))
        (out_dir / refs[2].path).write_bytes(_render_invoice(generated, invoice_fmt, rng, attack))

        truth = GroundTruthSet(
            set_id=generated.set_id,
            supplier_id=generated.supplier.party.party_id,
            contract_number=generated.supplier.contract.contract_number,
            documents=refs,
            purchase_order=generated.purchase_order,
            delivery_note=generated.delivery_note,
            invoice=generated.invoice,
            discrepancies=generated.discrepancies,
            decision=generated.decision,
            variations=generated.variations,
            attack=attack,
        )
        _write_json(
            out_dir / "ground_truth" / "sets" / f"{generated.set_id}.json",
            truth.model_dump(mode="json"),
        )

        counters["decision"][generated.decision.value] += 1
        counters["discrepancy"].update(d.type.value for d in generated.discrepancies)
        counters["invoice"][invoice_fmt.value] += 1
        counters["delivery"][delivery_fmt.value] += 1
        counters["variation"].update(generated.variations)
        if progress:
            progress(index, n_sets)

    manifest = Manifest(
        generator_version=__version__,
        seed=seed,
        n_sets=n_sets,
        n_suppliers=n_suppliers,
        p_discrepant=p_discrepant,
        decisions=dict(sorted(counters["decision"].items())),
        discrepancy_counts=dict(sorted(counters["discrepancy"].items())),
        invoice_formats=dict(sorted(counters["invoice"].items())),
        delivery_note_formats=dict(sorted(counters["delivery"].items())),
        variations=dict(sorted(counters["variation"].items())),
        attacks=dict(sorted(attack_counts.items())),
    )
    _write_json(out_dir / "manifest.json", manifest.model_dump(mode="json"))
    return manifest
