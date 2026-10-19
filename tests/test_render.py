from __future__ import annotations

import random

import pymupdf
from drafthorse.models.document import Document

from belegfluss.domain.documents import DocumentFormat
from belegfluss.storage.documents import sniff_format
from belegfluss.synth.render_pdf import (
    render_contract_pdf,
    render_delivery_note_pdf,
    render_invoice_pdf,
)
from belegfluss.synth.render_xml import XRECHNUNG_GUIDELINE, render_invoice_xml, render_zugferd_pdf
from belegfluss.synth.scan import pdf_to_scan_png
from belegfluss.synth.scenarios import generate_set
from belegfluss.synth.world import World


def _pdf_text(data: bytes) -> str:
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        return "\n".join(page.get_text() for page in doc)


def test_xrechnung_xml_round_trips(world: World) -> None:
    invoice = generate_set(random.Random(2), world, 1).invoice
    xml = render_invoice_xml(invoice)  # serialize() validates against the EN 16931 XSD
    parsed = Document.parse(xml)
    assert parsed.context.guideline_parameter.id._text == XRECHNUNG_GUIDELINE
    assert parsed.header.id._text == invoice.invoice_number
    assert parsed.trade.agreement.buyer_reference._text == invoice.po_number
    summation = parsed.trade.settlement.monetary_summation
    assert summation.grand_total._amount == invoice.stated_totals.gross
    assert sniff_format(xml) == (DocumentFormat.XRECHNUNG_CII, None)


def test_zugferd_pdf_embeds_xml(world: World) -> None:
    invoice = generate_set(random.Random(4), world, 2).invoice
    hybrid = render_zugferd_pdf(invoice, render_invoice_pdf(invoice))
    assert sniff_format(hybrid) == (DocumentFormat.ZUGFERD_PDF, "factur-x.xml")


def test_pdfs_contain_key_fields(world: World) -> None:
    generated = generate_set(random.Random(6), world, 3)
    invoice_text = _pdf_text(render_invoice_pdf(generated.invoice))
    assert generated.invoice.invoice_number in invoice_text
    assert generated.invoice.po_number in invoice_text
    assert "Rechnungsbetrag" in invoice_text
    note_text = _pdf_text(render_delivery_note_pdf(generated.delivery_note))
    assert generated.delivery_note.delivery_note_number in note_text
    contract_text = _pdf_text(render_contract_pdf(generated.supplier.contract))
    assert "Anlage 1" in contract_text and "Zahlungsbedingungen" in contract_text


def test_scan_is_a_png(world: World) -> None:
    generated = generate_set(random.Random(9), world, 4)
    png = pdf_to_scan_png(render_delivery_note_pdf(generated.delivery_note), random.Random(1))
    assert sniff_format(png) == (DocumentFormat.SCAN, None)
