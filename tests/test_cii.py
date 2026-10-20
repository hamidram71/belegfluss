from __future__ import annotations

import random

import pytest

from belegfluss.extraction.cii import UNRESOLVED, EInvoiceParseError, embedded_xml, parse_cii
from belegfluss.master_data import MasterData
from belegfluss.synth.render_pdf import render_invoice_pdf
from belegfluss.synth.render_xml import render_invoice_xml, render_zugferd_pdf
from belegfluss.synth.scenarios import generate_set
from belegfluss.synth.world import World


def test_every_generated_xml_invoice_round_trips_exactly(world: World, master: MasterData) -> None:
    rng = random.Random(21)
    for index in range(1, 151):
        invoice = generate_set(rng, world, index).invoice
        assert parse_cii(render_invoice_xml(invoice), master) == invoice


def test_zugferd_embedded_xml_round_trips(world: World, master: MasterData) -> None:
    invoice = generate_set(random.Random(22), world, 1).invoice
    hybrid = render_zugferd_pdf(invoice, render_invoice_pdf(invoice))
    assert parse_cii(embedded_xml(hybrid), master) == invoice


def test_unknown_supplier_is_marked_unresolved(world: World) -> None:
    invoice = generate_set(random.Random(23), world, 1).invoice
    empty = MasterData(buyer=world.buyer, suppliers=[], products=[])
    assert parse_cii(render_invoice_xml(invoice), empty).seller.party_id == UNRESOLVED


def test_external_entities_are_not_resolved(master: MasterData) -> None:
    xxe = b"""<?xml version="1.0"?>
<!DOCTYPE r [<!ENTITY secret SYSTEM "file:///etc/passwd">]>
<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100">
&secret;</rsm:CrossIndustryInvoice>"""
    with pytest.raises(EInvoiceParseError) as error:
        parse_cii(xxe, master)
    assert "root:" not in str(error.value)


@pytest.mark.parametrize("payload", [b"<not-closed", b"<x xmlns='urn:other'/>"])
def test_invalid_documents_raise(master: MasterData, payload: bytes) -> None:
    with pytest.raises(EInvoiceParseError):
        parse_cii(payload, master)


def test_plain_pdf_has_no_embedded_xml(world: World) -> None:
    invoice = generate_set(random.Random(24), world, 1).invoice
    with pytest.raises(EInvoiceParseError):
        embedded_xml(render_invoice_pdf(invoice))
