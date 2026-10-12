"""Generación de PDF a partir de plantillas HTML (xhtml2pdf, sin dependencias del sistema)."""

import io

from django.http import HttpResponse
from django.template.loader import render_to_string
from xhtml2pdf import pisa


def render_pdf(template: str, context: dict) -> bytes:
    html = render_to_string(template, context)
    buffer = io.BytesIO()
    result = pisa.CreatePDF(html, dest=buffer, encoding="utf-8")
    if result.err:
        raise RuntimeError("No se pudo generar el PDF")
    return buffer.getvalue()


def pdf_response(template: str, context: dict, filename: str, inline=True) -> HttpResponse:
    response = HttpResponse(render_pdf(template, context), content_type="application/pdf")
    disposition = "inline" if inline else "attachment"
    response["Content-Disposition"] = f'{disposition}; filename="{filename}"'
    return response
