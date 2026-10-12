"""Libro electrónico: Registro de Ventas e Ingresos 14.1 (RF-FAC-08).

Formato de texto plano separado por "|" según la estructura PLE de SUNAT.
Los archivos se marcan como EJEMPLO porque provienen del simulador (sección 12).
"""

from datetime import date
from decimal import Decimal

from .models import DocType, Invoice


def _fmt(v: Decimal) -> str:
    return f"{Decimal(v):.2f}"


def sales_register(property_obj, year: int, month: int) -> str:
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)
    period = f"{year}{month:02d}00"
    lines = []
    invoices = (
        Invoice.all_objects.filter(property=property_obj, issue_date__gte=start, issue_date__lt=end)
        .select_related("series", "related_invoice__series")
        .order_by("issue_date", "series__code", "number")
    )
    for i, inv in enumerate(invoices, start=1):
        sign = -1 if inv.doc_type == DocType.CREDIT_NOTE else 1
        voided = inv.status == Invoice.Status.VOIDED

        def amt(v, sign=sign, voided=voided):
            return _fmt(0) if voided else _fmt(Decimal(v) * sign)

        ref = inv.related_invoice
        fields = [
            period,  # 1 periodo
            f"M{i:06d}",  # 2 CUO
            f"M{i:06d}",  # 3 correlativo del asiento
            inv.issue_date.strftime("%d/%m/%Y"),  # 4 fecha de emisión
            inv.due_date.strftime("%d/%m/%Y") if inv.due_date else "",  # 5 vencimiento
            inv.doc_type,  # 6 tipo de comprobante
            inv.series.code,  # 7 serie
            str(inv.number),  # 8 número
            "",  # 9 consolidado
            inv.customer_doc_type,  # 10 tipo doc cliente
            inv.customer_doc or "-",  # 11 número doc cliente
            inv.customer_name[:100],  # 12 razón social
            amt(inv.export_amount),  # 13 valor facturado exportación
            amt(inv.taxed_amount),  # 14 base imponible gravada
            "0.00",  # 15 descuento base
            amt(inv.igv),  # 16 IGV
            "0.00",  # 17 descuento IGV
            amt(inv.exempt_amount),  # 18 exonerada
            "0.00",  # 19 inafecta
            "0.00",  # 20 ISC
            "0.00",  # 21 base arroz pilado
            "0.00",  # 22 IVAP
            "0.00",  # 23 ICBPER
            amt(inv.other_charges),  # 24 otros tributos y cargos
            amt(inv.total),  # 25 importe total
            inv.currency,  # 26 moneda
            f"{inv.exchange_rate:.3f}",  # 27 tipo de cambio
            ref.issue_date.strftime("%d/%m/%Y") if ref else "",  # 28 fecha comprobante modificado
            ref.doc_type if ref else "",  # 29 tipo comprobante modificado
            ref.series.code if ref else "",  # 30 serie modificado
            str(ref.number) if ref else "",  # 31 número modificado
            "",  # 32 identificación del contrato
            "",  # 33 error tipo 1
            "1",  # 34 indicador medio de pago
            "2" if voided else "1",  # 35 estado (1 = válido, 2 = anulado)
        ]
        lines.append("|".join(fields) + "|")
    return "\n".join(lines) + ("\n" if lines else "")


def ple_filename(property_obj, year, month, has_data=True) -> str:
    # LE + RUC + periodo + libro 140100 + indicadores
    return f"LE{property_obj.ruc}{year}{month:02d}00140100001{1 if has_data else 0}11_EJEMPLO.txt"
