"""Documentos electrónicos en UBL 2.1 con la estructura que pide SUNAT (RF-FAC-01/03/09).

Se generan los XML de factura, boleta, notas de crédito y débito, resumen diario (RC),
comunicación de baja (RA), guía de remisión remitente (GRE, DespatchAdvice) y la constancia
de recepción (CDR, ApplicationResponse).

La firma es simulada: el `DigestValue` es el SHA-256 en base64 del documento sin firma (el
mismo valor que se imprime como "código hash"). No se usa un certificado digital real.
"""

import base64
import hashlib
import io
import zipfile
from datetime import datetime
from decimal import Decimal
from xml.etree import ElementTree as ET

from django.utils import timezone

NS = {
    "": None,
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "ext": "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
    "sac": "urn:sunat:names:specification:ubl:peru:schema:xsd:SunatAggregateComponents-1",
}
ROOT_NS = {
    "Invoice": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "CreditNote": "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2",
    "DebitNote": "urn:oasis:names:specification:ubl:schema:xsd:DebitNote-2",
    "DespatchAdvice": "urn:oasis:names:specification:ubl:schema:xsd:DespatchAdvice-2",
    "SummaryDocuments": "urn:sunat:names:specification:ubl:peru:schema:xsd:SummaryDocuments-1",
    "VoidedDocuments": "urn:sunat:names:specification:ubl:peru:schema:xsd:VoidedDocuments-1",
    "ApplicationResponse": "urn:oasis:names:specification:ubl:schema:xsd:ApplicationResponse-2",
}
for prefix, uri in NS.items():
    if uri:
        ET.register_namespace(prefix, uri)

DIGEST_PLACEHOLDER = "__DIGEST__"
TAX = {  # catálogo 05: código, nombre, código internacional
    "10": ("1000", "IGV", "VAT"),
    "20": ("9997", "EXO", "VAT"),
    "30": ("9998", "INA", "FRE"),
    "40": ("9995", "EXP", "FRE"),
}


def q(tag: str) -> str:
    prefix, name = tag.split(":")
    return f"{{{NS[prefix]}}}{name}"


def el(parent, tag, text=None, **attrs):
    node = ET.SubElement(parent, q(tag), {k.replace("_", ""): str(v) for k, v in attrs.items()})
    if text is not None:
        node.text = str(text)
    return node


def money(parent, tag, value, currency):
    return el(parent, tag, f"{Decimal(value):.2f}", currencyID=currency)


def _root(name):
    ET.register_namespace("", ROOT_NS[name])
    return ET.Element(f"{{{ROOT_NS[name]}}}{name}")


def _signature(root, ruc, name):
    ext = el(el(el(root, "ext:UBLExtensions"), "ext:UBLExtension"), "ext:ExtensionContent")
    sig = el(ext, "ds:Signature", Id="SignSIM")
    info = el(sig, "ds:SignedInfo")
    ref = el(info, "ds:Reference", URI="")
    el(ref, "ds:DigestMethod", Algorithm="http://www.w3.org/2001/04/xmlenc#sha256")
    el(ref, "ds:DigestValue", DIGEST_PLACEHOLDER)
    el(sig, "ds:SignatureValue", "FIRMA-SIMULADA-SIN-CERTIFICADO")
    cac_sig = el(root, "cac:Signature")
    el(cac_sig, "cbc:ID", "SignSIM")
    party = el(cac_sig, "cac:SignatoryParty")
    el(el(party, "cac:PartyIdentification"), "cbc:ID", ruc)
    el(el(party, "cac:PartyName"), "cbc:Name", name)


def _party(parent, tag, doc_type, doc, name, address=""):
    party = el(el(parent, tag), "cac:Party")
    el(el(party, "cac:PartyIdentification"), "cbc:ID", doc or "-", schemeID=doc_type)
    legal = el(party, "cac:PartyLegalEntity")
    el(legal, "cbc:RegistrationName", name)
    if address:
        el(el(el(legal, "cac:RegistrationAddress"), "cac:AddressLine"), "cbc:Line", address)
    return party


def finalize(root) -> tuple[str, str]:
    """Serializa, calcula el hash (DigestValue) y lo inserta. Devuelve (xml, hash)."""
    raw = ET.tostring(root, encoding="unicode")
    unsigned = raw.replace(f"<ds:DigestValue>{DIGEST_PLACEHOLDER}</ds:DigestValue>", "<ds:DigestValue/>")
    digest = base64.b64encode(hashlib.sha256(unsigned.encode("utf-8")).digest()).decode()
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + raw.replace(DIGEST_PLACEHOLDER, digest)
    return xml, digest


def digest_of(xml: str) -> str:
    """Recalcula el hash de un XML firmado (lo usa la SUNAT simulada para detectar alteraciones)."""
    body = xml.split("\n", 1)[1] if xml.startswith("<?xml") else xml
    start = body.find("<ds:DigestValue>")
    end = body.find("</ds:DigestValue>")
    if start < 0 or end < 0:
        return ""
    unsigned = body[:start] + "<ds:DigestValue/>" + body[end + len("</ds:DigestValue>") :]
    return base64.b64encode(hashlib.sha256(unsigned.encode("utf-8")).digest()).decode()


def declared_digest(xml: str) -> str:
    start = xml.find("<ds:DigestValue>")
    end = xml.find("</ds:DigestValue>")
    return xml[start + len("<ds:DigestValue>") : end] if start >= 0 and end > start else ""


# --------------------------------------------------------------------------
# Factura, boleta y notas
# --------------------------------------------------------------------------


def invoice_xml(inv) -> tuple[str, str]:
    prop = inv.property
    name = {"01": "Invoice", "03": "Invoice", "07": "CreditNote", "08": "DebitNote"}[inv.doc_type]
    root = _root(name)
    _signature(root, prop.ruc, prop.legal_name)
    el(root, "cbc:UBLVersionID", "2.1")
    el(root, "cbc:CustomizationID", "2.0")
    el(root, "cbc:ID", inv.full_number)
    el(root, "cbc:IssueDate", inv.issue_date.isoformat())
    el(root, "cbc:IssueTime", timezone.localtime(inv.created_at).strftime("%H:%M:%S"))
    if inv.due_date and name == "Invoice":
        el(root, "cbc:DueDate", inv.due_date.isoformat())
    if name == "Invoice":
        operation = "0201" if inv.export_amount and not inv.taxed_amount else "0101"
        el(root, "cbc:InvoiceTypeCode", inv.doc_type, listID=operation)
    for legend in inv.legends:
        if legend["code"].isdigit():
            el(root, "cbc:Note", legend["text"], languageLocaleID=legend["code"])
    el(root, "cbc:DocumentCurrencyCode", inv.currency)
    if inv.related_invoice_id:
        rel = inv.related_invoice
        disc = el(root, "cac:DiscrepancyResponse")
        el(disc, "cbc:ReferenceID", rel.full_number)
        el(disc, "cbc:ResponseCode", inv.note_reason_code)
        el(disc, "cbc:Description", inv.note_reason or "-")
        ref = el(el(root, "cac:BillingReference"), "cac:InvoiceDocumentReference")
        el(ref, "cbc:ID", rel.full_number)
        el(ref, "cbc:DocumentTypeCode", rel.doc_type)
    _party(root, "cac:AccountingSupplierParty", "6", prop.ruc, prop.legal_name, prop.address)
    _party(
        root,
        "cac:AccountingCustomerParty",
        inv.customer_doc_type,
        inv.customer_doc,
        inv.customer_name,
        inv.customer_address,
    )
    for adv in inv.advances.all():
        pp = el(root, "cac:PrepaidPayment")
        el(pp, "cbc:ID", adv.full_number, schemeID="02" if adv.doc_type == "01" else "03")
        money(pp, "cbc:PaidAmount", adv.total, inv.currency)
    if inv.prepaid_amount:
        allowance = el(root, "cac:AllowanceCharge")
        el(allowance, "cbc:ChargeIndicator", "false")
        el(allowance, "cbc:AllowanceChargeReasonCode", "04")  # descuento global por anticipos gravados
        money(allowance, "cbc:Amount", inv.prepaid_amount, inv.currency)
    tax_total = el(root, "cac:TaxTotal")
    money(tax_total, "cbc:TaxAmount", inv.igv, inv.currency)
    for code, amount in (("10", inv.taxed_amount), ("20", inv.exempt_amount), ("40", inv.export_amount)):
        if amount or (code == "10" and not inv.exempt_amount and not inv.export_amount):
            sub = el(tax_total, "cac:TaxSubtotal")
            money(sub, "cbc:TaxableAmount", amount, inv.currency)
            money(sub, "cbc:TaxAmount", inv.igv if code == "10" else 0, inv.currency)
            scheme = el(el(sub, "cac:TaxCategory"), "cac:TaxScheme")
            tax_id, tax_name, intl = TAX[code]
            el(scheme, "cbc:ID", tax_id)
            el(scheme, "cbc:Name", tax_name)
            el(scheme, "cbc:TaxTypeCode", intl)
    totals_tag = "cac:RequestedMonetaryTotal" if name == "DebitNote" else "cac:LegalMonetaryTotal"
    totals = el(root, totals_tag)
    money(
        totals,
        "cbc:LineExtensionAmount",
        inv.taxed_amount + inv.exempt_amount + inv.export_amount,
        inv.currency,
    )
    money(totals, "cbc:TaxInclusiveAmount", inv.total + inv.prepaid_amount - inv.other_charges, inv.currency)
    if inv.other_charges:
        money(totals, "cbc:ChargeTotalAmount", inv.other_charges, inv.currency)
    if inv.prepaid_amount:
        money(totals, "cbc:PrepaidAmount", inv.prepaid_amount, inv.currency)
    money(totals, "cbc:PayableAmount", inv.total, inv.currency)
    line_tag = {"Invoice": "InvoiceLine", "CreditNote": "CreditNoteLine", "DebitNote": "DebitNoteLine"}[name]
    qty_tag = {
        "Invoice": "InvoicedQuantity",
        "CreditNote": "CreditedQuantity",
        "DebitNote": "DebitedQuantity",
    }[name]
    for i, ln in enumerate(inv.lines.all(), start=1):
        line = el(root, f"cac:{line_tag}")
        el(line, "cbc:ID", i)
        el(line, f"cbc:{qty_tag}", f"{ln.quantity:.3f}", unitCode=ln.unit_code)
        money(line, "cbc:LineExtensionAmount", ln.base, inv.currency)
        price_ref = el(el(line, "cac:PricingReference"), "cac:AlternativeConditionPrice")
        money(price_ref, "cbc:PriceAmount", ln.unit_price, inv.currency)
        el(price_ref, "cbc:PriceTypeCode", "01")
        line_tax = el(line, "cac:TaxTotal")
        money(line_tax, "cbc:TaxAmount", ln.igv, inv.currency)
        sub = el(line_tax, "cac:TaxSubtotal")
        money(sub, "cbc:TaxableAmount", ln.base, inv.currency)
        money(sub, "cbc:TaxAmount", ln.igv, inv.currency)
        cat = el(sub, "cac:TaxCategory")
        el(cat, "cbc:Percent", "18.00" if ln.affectation == "10" else "0.00")
        el(cat, "cbc:TaxExemptionReasonCode", ln.affectation)
        scheme = el(cat, "cac:TaxScheme")
        tax_id, tax_name, intl = TAX.get(ln.affectation, TAX["10"])
        el(scheme, "cbc:ID", tax_id)
        el(scheme, "cbc:Name", tax_name)
        el(scheme, "cbc:TaxTypeCode", intl)
        el(el(line, "cac:Item"), "cbc:Description", ln.description)
        qty = ln.quantity or Decimal("1")
        money(
            el(line, "cac:Price"), "cbc:PriceAmount", (ln.base / qty).quantize(Decimal("0.01")), inv.currency
        )
    return finalize(root)


# --------------------------------------------------------------------------
# Resumen diario (RC) y comunicación de baja (RA)
# --------------------------------------------------------------------------


def summary_xml(prop, file_id, ref_date, items) -> tuple[str, str]:
    """items: [{"doc_type","number","receiver_doc_type","receiver_doc","total","igv","taxed","status"}].
    status (catálogo 19): 1 adicionar, 2 modificar, 3 anulado."""
    root = _root("SummaryDocuments")
    _signature(root, prop.ruc, prop.legal_name)
    el(root, "cbc:UBLVersionID", "2.0")
    el(root, "cbc:CustomizationID", "1.1")
    el(root, "cbc:ID", file_id)
    el(root, "cbc:ReferenceDate", ref_date.isoformat())
    el(root, "cbc:IssueDate", timezone.localdate().isoformat())
    _party(root, "cac:AccountingSupplierParty", "6", prop.ruc, prop.legal_name)
    for i, it in enumerate(items, start=1):
        line = el(root, "sac:SummaryDocumentsLine")
        el(line, "cbc:LineID", i)
        el(line, "cbc:DocumentTypeCode", it["doc_type"])
        el(line, "cbc:ID", it["number"])
        el(
            el(line, "cac:AccountingCustomerParty"),
            "cbc:CustomerAssignedAccountID",
            it["receiver_doc"] or "-",
        )
        el(el(line, "cac:Status"), "cbc:ConditionCode", it["status"])
        money(line, "sac:TotalAmount", it["total"], it.get("currency", "PEN"))
        tax = el(line, "cac:TaxTotal")
        money(tax, "cbc:TaxAmount", it["igv"], it.get("currency", "PEN"))
    return finalize(root)


def voided_xml(prop, file_id, ref_date, items) -> tuple[str, str]:
    """items: [{"doc_type","series","number","reason"}]."""
    root = _root("VoidedDocuments")
    _signature(root, prop.ruc, prop.legal_name)
    el(root, "cbc:UBLVersionID", "2.0")
    el(root, "cbc:CustomizationID", "1.0")
    el(root, "cbc:ID", file_id)
    el(root, "cbc:ReferenceDate", ref_date.isoformat())
    el(root, "cbc:IssueDate", timezone.localdate().isoformat())
    _party(root, "cac:AccountingSupplierParty", "6", prop.ruc, prop.legal_name)
    for i, it in enumerate(items, start=1):
        line = el(root, "sac:VoidedDocumentsLine")
        el(line, "cbc:LineID", i)
        el(line, "cbc:DocumentTypeCode", it["doc_type"])
        el(line, "sac:DocumentSerialID", it["series"])
        el(line, "sac:DocumentNumberID", it["number"])
        el(line, "sac:VoidReasonDescription", it["reason"])
    return finalize(root)


# --------------------------------------------------------------------------
# Guía de remisión remitente (DespatchAdvice)
# --------------------------------------------------------------------------


def despatch_xml(guide) -> tuple[str, str]:
    prop = guide.property
    root = _root("DespatchAdvice")
    _signature(root, prop.ruc, prop.legal_name)
    el(root, "cbc:UBLVersionID", "2.1")
    el(root, "cbc:CustomizationID", "2.0")
    el(root, "cbc:ID", guide.full_number)
    el(root, "cbc:IssueDate", guide.issue_date.isoformat())
    el(root, "cbc:IssueTime", timezone.localtime().strftime("%H:%M:%S"))
    el(root, "cbc:DespatchAdviceTypeCode", "09")
    if guide.notes:
        el(root, "cbc:Note", guide.notes)
    _party(root, "cac:DespatchSupplierParty", "6", prop.ruc, prop.legal_name)
    _party(
        root, "cac:DeliveryCustomerParty", guide.recipient_doc_type, guide.recipient_doc, guide.recipient_name
    )
    shipment = el(root, "cac:Shipment")
    el(shipment, "cbc:ID", "SUNAT_Envio")
    el(shipment, "cbc:HandlingCode", guide.reason)
    el(shipment, "cbc:HandlingInstructions", guide.get_reason_display())
    el(shipment, "cbc:GrossWeightMeasure", f"{guide.gross_weight:.3f}", unitCode="KGM")
    el(shipment, "cbc:TotalTransportHandlingUnitQuantity", guide.packages)
    stage = el(shipment, "cac:ShipmentStage")
    el(stage, "cbc:TransportModeCode", guide.transport_mode)
    el(el(stage, "cac:TransitPeriod"), "cbc:StartDate", guide.transfer_date.isoformat())
    if guide.transport_mode == "01":
        carrier = el(stage, "cac:CarrierParty")
        el(el(carrier, "cac:PartyIdentification"), "cbc:ID", guide.carrier_ruc, schemeID="6")
        el(el(carrier, "cac:PartyLegalEntity"), "cbc:RegistrationName", guide.carrier_name)
    else:
        driver = el(stage, "cac:DriverPerson")
        el(driver, "cbc:ID", guide.driver_doc, schemeID="1")
        el(driver, "cbc:FirstName", guide.driver_name)
        el(el(driver, "cac:IdentityDocumentReference"), "cbc:ID", guide.driver_license)
        el(
            el(el(stage, "cac:TransportMeans"), "cac:RoadTransport"),
            "cbc:LicensePlateID",
            guide.vehicle_plate,
        )
    delivery = el(shipment, "cac:Delivery")
    arrival = el(delivery, "cac:DeliveryAddress")
    el(arrival, "cbc:ID", guide.destination_ubigeo, schemeAgencyName="PE:INEI")
    el(el(arrival, "cac:AddressLine"), "cbc:Line", guide.destination_address)
    despatch = el(el(delivery, "cac:Despatch"), "cac:DespatchAddress")
    el(despatch, "cbc:ID", guide.origin_ubigeo, schemeAgencyName="PE:INEI")
    el(el(despatch, "cac:AddressLine"), "cbc:Line", guide.origin_address)
    for i, ln in enumerate(guide.lines.all(), start=1):
        line = el(root, "cac:DespatchLine")
        el(line, "cbc:ID", i)
        el(line, "cbc:DeliveredQuantity", f"{ln.quantity:.3f}", unitCode=ln.unit)
        el(el(line, "cac:OrderLineReference"), "cbc:LineID", i)
        item = el(line, "cac:Item")
        el(item, "cbc:Description", ln.description)
        if ln.code:
            el(el(item, "cac:SellersItemIdentification"), "cbc:ID", ln.code)
    return finalize(root)


# --------------------------------------------------------------------------
# Constancia de recepción (CDR)
# --------------------------------------------------------------------------


def cdr_xml(*, issuer_ruc, doc_id, receiver_doc, code, description, notes=(), ticket="") -> str:
    root = _root("ApplicationResponse")
    el(root, "cbc:UBLVersionID", "2.0")
    el(root, "cbc:CustomizationID", "1.0")
    el(root, "cbc:ID", ticket or datetime.now().strftime("%Y%m%d%H%M%S%f"))
    now = timezone.localtime()
    el(root, "cbc:IssueDate", now.date().isoformat())
    el(root, "cbc:IssueTime", now.strftime("%H:%M:%S"))
    el(root, "cbc:ResponseDate", now.date().isoformat())
    el(root, "cbc:ResponseTime", now.strftime("%H:%M:%S"))
    for note in notes:
        el(root, "cbc:Note", note)
    sender = el(root, "cac:SenderParty")
    el(el(sender, "cac:PartyIdentification"), "cbc:ID", "20131312955")  # RUC de SUNAT
    receiver = el(root, "cac:ReceiverParty")
    el(el(receiver, "cac:PartyIdentification"), "cbc:ID", issuer_ruc)
    response = el(root, "cac:DocumentResponse")
    resp = el(response, "cac:Response")
    el(resp, "cbc:ReferenceID", doc_id)
    el(resp, "cbc:ResponseCode", code)
    el(resp, "cbc:Description", description)
    ref = el(response, "cac:DocumentReference")
    el(ref, "cbc:ID", doc_id)
    if receiver_doc:
        el(el(el(response, "cac:RecipientParty"), "cac:PartyIdentification"), "cbc:ID", receiver_doc)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")


def zip_bytes(name: str, content: str) -> bytes:
    """SUNAT envía y devuelve los XML comprimidos en ZIP."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, content)
    return buf.getvalue()
