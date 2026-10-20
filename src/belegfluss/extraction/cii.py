"""Deterministic parser for EN 16931 invoices in UN/CEFACT CII syntax (XRechnung, ZUGFeRD).

Every field is read with an explicit XPath and its EN 16931 business term (BT) is named in a
comment, so each value can be traced to the standard. The XML parser is hardened against
XXE and entity-expansion attacks: invoices come from outside the company (see ADR 0005).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from lxml import etree
from pypdf import PdfReader

from belegfluss.domain.models import (
    Address,
    Invoice,
    InvoiceTotals,
    LineItem,
    Party,
    PaymentTerms,
)
from belegfluss.extraction.parsing import parse_date, parse_decimal, parse_payment_terms, parse_unit
from belegfluss.master_data import MasterData
from belegfluss.storage.documents import EINVOICE_ATTACHMENTS

NS = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
}
UNRESOLVED = "UNRESOLVED"


class EInvoiceParseError(ValueError):
    """The XML is not a parseable EN 16931 CII invoice."""


def _secure_parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
        remove_comments=True,
    )


def _text(node: etree._Element, path: str) -> str | None:
    found = node.xpath(path, namespaces=NS)
    if not found:
        return None
    value = found[0] if isinstance(found[0], str) else found[0].text
    return value.strip() if value else None


def _one(node: etree._Element, path: str, term: str) -> etree._Element:
    found = node.xpath(path, namespaces=NS)
    if not found:
        raise EInvoiceParseError(f"missing {term} ({path})")
    return found[0]


def _required(node: etree._Element, path: str, term: str) -> str:
    value = _text(node, path)
    if value is None:
        raise EInvoiceParseError(f"missing {term} ({path})")
    return value


def _party(node: etree._Element, role: str) -> tuple[str, Address, str | None, str | None]:
    name = _required(node, "ram:Name", f"{role} name")
    address = Address(
        street=_text(node, "ram:PostalTradeAddress/ram:LineOne") or "",
        postal_code=_text(node, "ram:PostalTradeAddress/ram:PostcodeCode") or "",
        city=_text(node, "ram:PostalTradeAddress/ram:CityName") or "",
        country_code=_text(node, "ram:PostalTradeAddress/ram:CountryID") or "DE",
    )
    vat_id = _text(node, "ram:SpecifiedTaxRegistration/ram:ID[@schemeID='VA']")
    email = _text(node, "ram:URIUniversalCommunication/ram:URIID")
    return name, address, vat_id, email


def parse_cii(xml: bytes, master: MasterData) -> Invoice:
    try:
        root = etree.fromstring(xml, parser=_secure_parser())
    except etree.XMLSyntaxError as exc:
        raise EInvoiceParseError(f"invalid XML: {exc}") from exc
    if root.tag != f"{{{NS['rsm']}}}CrossIndustryInvoice":
        raise EInvoiceParseError("root element is not rsm:CrossIndustryInvoice")

    header = "rsm:ExchangedDocument"
    invoice_number = _required(root, f"{header}/ram:ID", "BT-1 invoice number")
    trade = _one(root, "rsm:SupplyChainTradeTransaction", "trade transaction")
    agreement = "ram:ApplicableHeaderTradeAgreement"
    settlement = "ram:ApplicableHeaderTradeSettlement"

    issue_date = parse_date(
        _required(root, f"{header}/ram:IssueDateTime/udt:DateTimeString", "BT-2 issue date")
    )

    seller_node = _one(trade, f"{agreement}/ram:SellerTradeParty", "BG-4 seller")
    buyer_node = _one(trade, f"{agreement}/ram:BuyerTradeParty", "BG-7 buyer")
    s_name, s_address, s_vat, s_email = _party(seller_node, "BG-4 seller")
    b_name, b_address, b_vat, b_email = _party(buyer_node, "BG-7 buyer")

    iban = _text(
        trade,
        f"{settlement}/ram:SpecifiedTradeSettlementPaymentMeans"
        "/ram:PayeePartyCreditorFinancialAccount/ram:IBANID",
    )  # BT-84
    record = master.resolve_supplier(s_vat, s_name)
    seller = Party(
        party_id=record.party.party_id if record else UNRESOLVED,
        name=s_name,
        address=s_address,
        vat_id=s_vat,
        iban=iban,
        email=s_email,
    )
    buyer = (
        master.buyer
        if master.is_buyer(b_vat, b_name)
        else Party(party_id=UNRESOLVED, name=b_name, address=b_address, vat_id=b_vat, email=b_email)
    )

    po_number = _text(
        trade, f"{agreement}/ram:BuyerOrderReferencedDocument/ram:IssuerAssignedID"
    ) or _text(trade, f"{agreement}/ram:BuyerReference")  # BT-13, fallback BT-10
    contract_number = _text(
        trade, f"{agreement}/ram:ContractReferencedDocument/ram:IssuerAssignedID"
    )  # BT-12
    delivery_note_number = _text(
        trade,
        "ram:ApplicableHeaderTradeDelivery/ram:DespatchAdviceReferencedDocument"
        "/ram:IssuerAssignedID",
    )  # BT-16

    terms_text = _text(trade, f"{settlement}/ram:SpecifiedTradePaymentTerms/ram:Description")
    due_text = _text(
        trade, f"{settlement}/ram:SpecifiedTradePaymentTerms/ram:DueDateDateTime/udt:DateTimeString"
    )  # BT-9
    due_date = parse_date(due_text) if due_text else None
    fallback_days = (due_date - issue_date).days if due_date else None
    payment_terms = (
        parse_payment_terms(terms_text, fallback_days)
        if terms_text
        else PaymentTerms(net_days=fallback_days or 30)
    )
    if due_date is None:
        due_date = issue_date + timedelta(days=payment_terms.net_days)

    items = []
    for line in trade.xpath("ram:IncludedSupplyChainTradeLineItem", namespaces=NS):
        price = parse_decimal(
            _required(
                line,
                "ram:SpecifiedLineTradeAgreement/ram:NetPriceProductTradePrice/ram:ChargeAmount",
                "BT-146 item net price",
            )
        )
        basis = _text(
            line, "ram:SpecifiedLineTradeAgreement/ram:NetPriceProductTradePrice/ram:BasisQuantity"
        )  # BT-149: price may refer to e.g. 100 units
        if basis and parse_decimal(basis) not in (Decimal(0), Decimal(1)):
            price = price / parse_decimal(basis)
        quantity_path = "ram:SpecifiedLineTradeDelivery/ram:BilledQuantity"
        items.append(
            LineItem(
                position=int(
                    _required(
                        line, "ram:AssociatedDocumentLineDocument/ram:LineID", "BT-126 line id"
                    )
                ),
                sku=_text(line, "ram:SpecifiedTradeProduct/ram:SellerAssignedID") or "",  # BT-155
                description=_required(line, "ram:SpecifiedTradeProduct/ram:Name", "BT-153 name"),
                quantity=parse_decimal(_required(line, quantity_path, "BT-129 quantity")),
                unit=parse_unit(_text(line, f"{quantity_path}/@unitCode")),  # BT-130
                unit_price=price,
                vat_rate=parse_decimal(
                    _required(
                        line,
                        "ram:SpecifiedLineTradeSettlement/ram:ApplicableTradeTax"
                        "/ram:RateApplicablePercent",
                        "BT-152 VAT rate",
                    )
                ),
            )
        )
    if not items:
        raise EInvoiceParseError("invoice has no line items (BG-25)")

    summation = f"{settlement}/ram:SpecifiedTradeSettlementHeaderMonetarySummation"
    totals = InvoiceTotals(
        net=parse_decimal(_required(trade, f"{summation}/ram:TaxBasisTotalAmount", "BT-109")),
        vat=parse_decimal(_required(trade, f"{summation}/ram:TaxTotalAmount", "BT-110")),
        gross=parse_decimal(_required(trade, f"{summation}/ram:GrandTotalAmount", "BT-112")),
    )
    return Invoice(
        invoice_number=invoice_number,
        issue_date=issue_date,
        due_date=due_date,
        seller=seller,
        buyer=buyer,
        po_number=po_number or "",
        delivery_note_number=delivery_note_number or "",
        contract_number=contract_number,
        items=items,
        payment_terms=payment_terms,
        stated_totals=totals,
    )


def embedded_xml(pdf: bytes) -> bytes:
    """Return the e-invoice XML embedded in a ZUGFeRD / Factur-X PDF."""
    reader = PdfReader(BytesIO(pdf))
    for name, contents in reader.attachments.items():
        if name.lower() in EINVOICE_ATTACHMENTS and contents:
            return contents[0]
    raise EInvoiceParseError("PDF has no embedded e-invoice XML")
