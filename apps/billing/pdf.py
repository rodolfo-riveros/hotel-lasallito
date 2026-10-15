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


def _validity_url() -> str:
    from django.conf import settings

    return f"{getattr(settings, 'SITE_URL', '').rstrip('/')}/consulta-comprobante/"


def invoice_pdf_bytes(invoice) -> bytes:
    return render_pdf(
        "billing/invoice_pdf.html",
        {
            "inv": invoice,
            "property": invoice.property,
            "qr": qr_data_uri(invoice),
            "validity_url": _validity_url(),
        },
    )


def guide_pdf_bytes(guide) -> bytes:
    """Representación impresa de la guía de remisión (RF-FAC-09) con QR de consulta."""
    p = guide.property
    text = "|".join(
        [p.ruc, "09", guide.series.code, str(guide.number), guide.issue_date.strftime("%Y-%m-%d"), guide.hash]
    )
    img = qrcode.make(text, box_size=4, border=1)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    return render_pdf(
        "billing/guide_pdf.html",
        {"g": guide, "property": p, "qr": qr, "lines": guide.lines.all(), "validity_url": _validity_url()},
    )
