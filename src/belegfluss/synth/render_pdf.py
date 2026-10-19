"""Render documents as German business PDFs with ReportLab.

Layouts deliberately differ between suppliers (accent colour, column order, header style),
so that extraction cannot rely on a single fixed template.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from belegfluss.domain.identifiers import format_iban
from belegfluss.domain.models import DeliveryNote, FrameworkContract, Invoice, Party
from belegfluss.domain.money import format_decimal_de, format_eur_de, format_unit_price_de

# ReportLab ships without type hints; a story is a list of flowables.
Story = list[Any]

_ACCENTS = ("#1f4e79", "#7a2e2e", "#2e5e3a", "#5b3c88", "#8a5a00", "#333333")

_BASE = getSampleStyleSheet()
STYLES = {
    "body": ParagraphStyle("body", parent=_BASE["Normal"], fontSize=9, leading=12),
    "small": ParagraphStyle(
        "small", parent=_BASE["Normal"], fontSize=7, leading=9, textColor=colors.HexColor("#555555")
    ),
    "title": ParagraphStyle(
        "title", parent=_BASE["Heading1"], fontSize=16, leading=20, spaceAfter=4
    ),
    "h2": ParagraphStyle(
        "h2", parent=_BASE["Heading2"], fontSize=11, leading=14, spaceBefore=8, spaceAfter=3
    ),
    "right": ParagraphStyle(
        "right", parent=_BASE["Normal"], fontSize=9, leading=12, alignment=TA_RIGHT
    ),
}


def _p(text: str, style: str = "body") -> Paragraph:
    return Paragraph(escape(text).replace("\n", "<br/>"), STYLES[style])


def _accent(party: Party) -> colors.Color:
    return colors.HexColor(_ACCENTS[int(party.party_id[-2:]) % len(_ACCENTS)])


def _address_lines(party: Party) -> str:
    a = party.address
    return f"{party.name}\n{a.street}\n{a.postal_code} {a.city}"


def _letterhead(sender: Party, recipient: Party, title: str, meta: list[tuple[str, str]]) -> Story:
    accent = _accent(sender)
    head = Table(
        [
            [
                Paragraph(
                    f'<font color="{accent.hexval()}" size="14"><b>{escape(sender.name)}</b>'
                    "</font>",
                    STYLES["body"],
                ),
                _p(
                    f"{sender.address.street} · {sender.address.postal_code} {sender.address.city}",
                    "small",
                ),
            ]
        ],
        colWidths=[105 * mm, 65 * mm],
    )
    head.setStyle(
        TableStyle(
            [("VALIGN", (0, 0), (-1, -1), "BOTTOM"), ("LINEBELOW", (0, 0), (-1, 0), 1.2, accent)]
        )
    )
    meta_table = Table([[_p(k), _p(v)] for k, v in meta], colWidths=[32 * mm, 40 * mm])
    meta_table.setStyle(
        TableStyle([("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)])
    )
    address_block = [
        _p(
            f"{sender.name} · {sender.address.street} · {sender.address.postal_code} "
            f"{sender.address.city}",
            "small",
        ),
        Spacer(1, 2 * mm),
        _p(_address_lines(recipient)),
    ]
    block = Table([[address_block, meta_table]], colWidths=[98 * mm, 72 * mm])
    block.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return [head, Spacer(1, 10 * mm), block, Spacer(1, 10 * mm), _p(title, "title")]


def _grid(
    data: list[list[object]], widths: list[float], accent: colors.Color, right_cols: tuple[int, ...]
) -> Table:
    table = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), accent),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#bbbbbb")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    style += [("ALIGN", (c, 0), (c, -1), "RIGHT") for c in right_cols]
    table.setStyle(TableStyle(style))
    return table


def _footer(party: Party) -> Story:
    parts = [party.name, f"USt-IdNr.: {party.vat_id}"]
    if party.iban:
        parts.append(f"IBAN: {format_iban(party.iban)}")
    if party.email:
        parts.append(party.email)
    return [Spacer(1, 8 * mm), _p(" · ".join(parts), "small")]


def _signatures(left: str, right: str) -> Table:
    line = "_" * 34
    table = Table(
        [[_p(line), _p(line)], [_p(left, "small"), _p(right, "small")]],
        colWidths=[85 * mm, 85 * mm],
    )
    table.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    return table


def _build(story: Story) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )
    doc.build(story)
    return buffer.getvalue()


def render_invoice_pdf(invoice: Invoice) -> bytes:
    seller = invoice.seller
    accent = _accent(seller)
    meta = [
        ("Rechnungsnr.:", invoice.invoice_number),
        ("Rechnungsdatum:", f"{invoice.issue_date:%d.%m.%Y}"),
        ("Ihre Bestellung:", invoice.po_number),
        ("Lieferschein:", invoice.delivery_note_number),
    ]
    if invoice.contract_number:
        meta.append(("Rahmenvertrag:", invoice.contract_number))
    story = _letterhead(seller, invoice.buyer, "Rechnung", meta)
    sku_first = int(seller.party_id[-1]) % 2 == 0
    header: list[object] = (
        ["Pos.", "Art.-Nr.", "Bezeichnung"] if sku_first else ["Pos.", "Bezeichnung", "Art.-Nr."]
    )
    header += ["Menge", "Einh.", "Einzelpreis", "USt.", "Gesamt"]
    rows: list[list[object]] = [header]
    for item in invoice.items:
        text_cols: list[object] = [item.sku, _p(item.description)]
        if not sku_first:
            text_cols.reverse()
        rows.append(
            [
                str(item.position),
                *text_cols,
                format_decimal_de(item.quantity),
                item.unit.label_de,
                format_unit_price_de(item.unit_price),
                f"{format_decimal_de(item.vat_rate)} %",
                format_eur_de(item.net_amount),
            ]
        )
    widths = [10, 26, 54, 16, 11, 20, 11, 22] if sku_first else [10, 54, 26, 16, 11, 20, 11, 22]
    story.append(_grid(rows, [w * mm for w in widths], accent, (3, 5, 6, 7)))

    totals = invoice.stated_totals
    breakdown = invoice.vat_breakdown()
    total_rows = [["Summe netto", format_eur_de(totals.net)]]
    if len(breakdown) == 1:
        total_rows.append(
            [f"zzgl. {format_decimal_de(breakdown[0].rate)} % USt.", format_eur_de(totals.vat)]
        )
    else:
        total_rows += [
            [
                f"zzgl. {format_decimal_de(b.rate)} % USt. auf {format_eur_de(b.basis)}",
                format_eur_de(b.amount),
            ]
            for b in breakdown
        ]
    total_rows.append(["Rechnungsbetrag", format_eur_de(totals.gross)])
    total_table = Table(total_rows, colWidths=[60 * mm, 30 * mm], hAlign="RIGHT")
    total_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("LINEABOVE", (0, -1), (-1, -1), 0.8, accent),
            ]
        )
    )
    story += [Spacer(1, 4 * mm), total_table, Spacer(1, 6 * mm)]
    story.append(
        KeepTogether(
            [
                _p(
                    f"Leistungsdatum entspricht dem Lieferdatum laut Lieferschein "
                    f"{invoice.delivery_note_number}."
                ),
                _p(f"{invoice.payment_terms.describe_de()} Fällig am {invoice.due_date:%d.%m.%Y}."),
                _p(
                    "Bitte überweisen Sie den Betrag unter Angabe der Rechnungsnummer auf "
                    f"folgendes Konto: IBAN {format_iban(seller.iban or '')}"
                ),
            ]
        )
    )
    story += _footer(seller)
    return _build(story)


def render_delivery_note_pdf(note: DeliveryNote) -> bytes:
    supplier = note.supplier
    accent = _accent(supplier)
    meta = [
        ("Lieferschein-Nr.:", note.delivery_note_number),
        ("Lieferdatum:", f"{note.delivery_date:%d.%m.%Y}"),
        ("Ihre Bestellung:", note.po_number),
    ]
    story = _letterhead(supplier, note.buyer, "Lieferschein", meta)
    rows: list[list[object]] = [["Pos.", "Art.-Nr.", "Bezeichnung", "Menge", "Einh."]]
    rows += [
        [str(i.position), i.sku, _p(i.description), format_decimal_de(i.quantity), i.unit.label_de]
        for i in note.items
    ]
    story.append(_grid(rows, [w * mm for w in (12, 32, 92, 18, 16)], accent, (3,)))
    story += [
        Spacer(1, 10 * mm),
        _p("Ware vollständig und in einwandfreiem Zustand erhalten:"),
        Spacer(1, 12 * mm),
        _signatures("Datum, Unterschrift Empfänger", "Name in Druckbuchstaben"),
    ]
    story += _footer(supplier.model_copy(update={"iban": None}))
    return _build(story)


def render_contract_pdf(contract: FrameworkContract) -> bytes:
    story: Story = [
        _p("Rahmenliefervertrag", "title"),
        _p(f"Vertragsnummer {contract.contract_number}"),
        Spacer(1, 4 * mm),
        _p(f"zwischen\n{_address_lines(contract.buyer)}\n– nachfolgend „Besteller“ –"),
        Spacer(1, 3 * mm),
        _p(f"und\n{_address_lines(contract.supplier)}\n– nachfolgend „Lieferant“ –"),
    ]
    accent = _accent(contract.supplier)
    for clause in contract.clauses:
        if clause.clause_id.startswith("Anlage"):
            continue
        story += [_p(f"{clause.clause_id} {clause.title}", "h2"), _p(clause.text)]
    story += [
        Spacer(1, 10 * mm),
        _p(f"Heilbronn, den {contract.valid_from:%d.%m.%Y}"),
        Spacer(1, 10 * mm),
        _signatures("Besteller", "Lieferant"),
        Spacer(1, 10 * mm),
        _p("Anlage 1 – Preisliste (Nettopreise, Festpreise gemäß § 3)", "h2"),
    ]
    rows: list[list[object]] = [["Art.-Nr.", "Bezeichnung", "Einheit", "Preis netto"]]
    rows += [
        [a.sku, _p(a.description), a.unit.label_de, format_unit_price_de(a.unit_price)]
        for a in contract.price_agreements
    ]
    story.append(_grid(rows, [w * mm for w in (34, 92, 18, 26)], accent, (3,)))
    return _build(story)
