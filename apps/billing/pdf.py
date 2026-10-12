"""Representación impresa del comprobante con QR y marca de agua de simulación (RF-FAC-03, RF-SIM-06)."""

import base64
import io

import qrcode

from apps.core.pdf import render_pdf


def qr_data_uri(invoice) -> str:
    p = invoice.property
    text = "|".join(
        [
            p.ruc,
            invoice.doc_type,
            invoice.series.code,
            str(invoice.number),
            f"{invoice.igv:.2f}",
            f"{invoice.total:.2f}",
            invoice.issue_date.strftime("%Y-%m-%d"),
            invoice.customer_doc_type,
            invoice.customer_doc or "-",
        ]
    )
    img = qrcode.make(text, box_size=4, border=1)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def invoice_pdf_bytes(invoice) -> bytes:
    return render_pdf(
        "billing/invoice_pdf.html", {"inv": invoice, "property": invoice.property, "qr": qr_data_uri(invoice)}
    )
