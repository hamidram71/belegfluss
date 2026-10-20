"""Render invoices as EN 16931 e-invoices in UN/CEFACT CII syntax.

* ``XRECHNUNG_GUIDELINE``: the German XRechnung CIUS, used for pure XML invoices.
* ``EN16931_GUIDELINE``: the plain EN 16931 profile, embedded in ZUGFeRD hybrid PDFs.

Output is validated against the Factur-X EN 16931 XSD by drafthorse. XRechnung business
rules (KoSIT Schematron) are not checked yet; see "Known limitations" in the README.
"""

from __future__ import annotations

from decimal import Decimal

from drafthorse.models.accounting import ApplicableTradeTax
from drafthorse.models.document import Document
from drafthorse.models.party import TaxRegistration
from drafthorse.models.payment import PaymentMeans, PaymentTerms
from drafthorse.models.tradelines import LineItem as CiiLineItem
from drafthorse.pdf import attach_xml

from belegfluss.domain.models import Invoice, Party

XRECHNUNG_GUIDELINE = "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0"
EN16931_GUIDELINE = "urn:cen.eu:en16931:2017"
SEPA_CREDIT_TRANSFER = "58"
COMMERCIAL_INVOICE = "380"


def _set_party(target: object, party: Party, with_vat: bool) -> None:
    target.name = party.name  # type: ignore[attr-defined]
    address = target.address  # type: ignore[attr-defined]
    address.line_one = party.address.street
    address.postcode = party.address.postal_code
    address.city_name = party.address.city
    address.country_id = party.address.country_code
    if with_vat and party.vat_id:
        target.tax_registrations.add(TaxRegistration(id=("VA", party.vat_id)))  # type: ignore[attr-defined]
    if party.email:
        target.electronic_address.uri_ID = ("EM", party.email)  # type: ignore[attr-defined]


def build_cii_document(invoice: Invoice, guideline: str = XRECHNUNG_GUIDELINE) -> Document:
    doc = Document()
    doc.context.guideline_parameter.id = guideline
    doc.header.id = invoice.invoice_number
    doc.header.type_code = COMMERCIAL_INVOICE
    doc.header.issue_date_time = invoice.issue_date

    agreement = doc.trade.agreement
    agreement.buyer_reference = invoice.po_number  # BT-10, mandatory in XRechnung
    agreement.buyer_order.issuer_assigned_id = invoice.po_number  # BT-13
    if invoice.contract_number:
        agreement.contract.issuer_assigned_id = invoice.contract_number  # BT-12
    _set_party(agreement.seller, invoice.seller, with_vat=True)
    _set_party(agreement.buyer, invoice.buyer, with_vat=False)

    doc.trade.delivery.despatch_advice.issuer_assigned_id = invoice.delivery_note_number  # BT-16

    settlement = doc.trade.settlement
    settlement.currency_code = "EUR"
    means = PaymentMeans()
    means.type_code = SEPA_CREDIT_TRANSFER
    means.payee_account.iban = invoice.seller.iban
    settlement.payment_means.add(means)
    terms = PaymentTerms()
    terms.description = invoice.payment_terms.describe_de()
    terms.due = invoice.due_date
    settlement.terms.add(terms)

    for item in invoice.items:
        line = CiiLineItem()
        line.document.line_id = str(item.position)
        line.product.seller_assigned_id = item.sku
        line.product.name = item.description
        line.agreement.net.amount = item.unit_price
        line.delivery.billed_quantity = (item.quantity, item.unit.value)
        line.settlement.trade_tax.type_code = "VAT"
        line.settlement.trade_tax.category_code = "S"
        line.settlement.trade_tax.rate_applicable_percent = item.vat_rate
        line.settlement.monetary_summation.total_amount = item.net_amount
        doc.trade.items.add(line)

    for vat in invoice.vat_breakdown():
        tax = ApplicableTradeTax()
        tax.calculated_amount = vat.amount
        tax.basis_amount = vat.basis
        tax.type_code = "VAT"
        tax.category_code = "S"
        tax.rate_applicable_percent = vat.rate
        settlement.trade_tax.add(tax)

    # Stated totals are written as they are, even when they are (deliberately) inconsistent.
    totals = invoice.stated_totals
    summation = settlement.monetary_summation
    summation.line_total = totals.net
    summation.charge_total = Decimal("0.00")
    summation.allowance_total = Decimal("0.00")
    summation.tax_basis_total = totals.net
    summation.tax_total = (totals.vat, "EUR")
    summation.grand_total = totals.gross
    summation.due_amount = totals.gross
    return doc


def render_invoice_xml(invoice: Invoice, guideline: str = XRECHNUNG_GUIDELINE) -> bytes:
    """Serialise and XSD-validate a CII invoice."""
    xml: bytes = build_cii_document(invoice, guideline).serialize(schema="FACTUR-X_EN16931")
    return xml


def render_zugferd_pdf(invoice: Invoice, visual_pdf: bytes) -> bytes:
    """Embed the EN 16931 XML into the human-readable PDF (ZUGFeRD / Factur-X hybrid)."""
    xml = render_invoice_xml(invoice, EN16931_GUIDELINE)
    result: bytes = attach_xml(visual_pdf, xml, level="EN 16931")
    return result
