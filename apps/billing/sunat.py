"""Adaptadores SUNAT (patrón adaptador, sección 9) y la SUNAT simulada.

`SUNAT_MODE=simulator` usa `SimulatorAdapter`, una SUNAT interna que se comporta como la real
sin que nadie la configure:

- recibe el XML UBL 2.1, verifica que no fue alterado y lo valida con las reglas de SUNAT
  (tipo y documento del receptor, plazos, series, totales, IGV, exportación, notas, duplicados);
- responde al instante con la constancia de recepción (CDR) para facturas, boletas y notas;
- para resumen diario (RC), comunicación de baja (RA) y guía de remisión (GRE) devuelve un ticket
  que se procesa unos segundos después, y se consulta con `get_status`, como en SUNAT;
- guarda lo recibido en `SunatRegistry`, que sirve para detectar duplicados y para la consulta
  pública de validez del comprobante.

La única falla externa es la caída de conexión, que activa el evento "Falla SUNAT" del modo aula.
Los códigos de respuesta siguen el catálogo de errores de SUNAT (algunos mensajes simplificados).
Para facturar de verdad se implementa `OSEAdapter` sin tocar el resto del sistema.
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import ubl
from .validators import dni_is_valid, ruc_is_valid

CODES = {
    "0": "La {doc} {id} ha sido aceptada",
    "0100": "El sistema no puede responder su solicitud. Intente nuevamente o comuníquese con su administrador",
    "0127": "El ticket no existe",
    "1001": "El número de serie no corresponde al tipo de comprobante",
    "1033": "El comprobante fue registrado previamente con otros datos",
    "2017": "El número de documento de identidad del receptor debe ser RUC",
    "2020": "El RUC del receptor no está activo en el padrón de contribuyentes",
    "2105": "El comprobante que desea dar de baja no ha sido informado o ya está de baja",
    "2108": "Presentación fuera de fecha: el plazo de envío es de 3 días calendario",
    "2116": "El tipo de documento del comprobante que modifica no corresponde a la serie de la nota",
    "2329": "La fecha de emisión se encuentra fuera del límite permitido",
    "2335": "El documento electrónico ingresado ha sido alterado",
    "2375": "La fecha de emisión del comprobante a dar de baja excede el plazo de 7 días",
    "2524": "El comprobante que se modifica no ha sido informado a SUNAT o está de baja",
    "2525": "El importe de la nota de crédito excede el saldo del comprobante que modifica",
    "2642": "Las operaciones de exportación requieren un documento de identidad de no domiciliado",
    "2800": "El dato ingresado en el tipo de documento de identidad del receptor no está permitido",
    "3105": "El importe total no coincide con la suma de valores de venta, tributos y cargos",
    "3111": "El IGV de la línea {line} no corresponde al 18 % del valor de venta",
    "3301": "La guía requiere RUC válido y razón social del transportista (transporte público)",
    "3302": "La guía requiere placa, DNI y licencia del conductor (transporte privado)",
    "3303": "La fecha de inicio del traslado no puede ser anterior a la fecha de emisión",
    "3304": "El peso bruto total y la cantidad de los bienes deben ser mayores que cero",
    "3305": "El ubigeo de partida o de llegada no es válido",
    "3306": "En el traslado entre establecimientos el destinatario debe ser el mismo emisor",
    "4001": "El receptor tiene la condición NO HABIDO en el padrón de contribuyentes",
    "4095": "No se consignó la dirección del adquirente",
}
SEND_DAYS = 3  # plazo de envío de facturas y notas asociadas
VOID_DAYS = 7  # plazo para comunicar la baja
PLATE = re.compile(r"^[A-Z0-9]{3}-?[A-Z0-9]{3}$")


@dataclass
class SunatResult:
    accepted: bool
    code: str = ""
    message: str = ""
    connection_error: bool = False
    ticket: str = ""
    observations: list = field(default_factory=list)
    cdr: str = ""
    processing: bool = False


def msg(code, **kw) -> str:
    return CODES[code].format(**kw) if kw else CODES[code]


class SunatAdapter:
    def send(self, invoice) -> SunatResult:  # pragma: no cover - interfaz
        raise NotImplementedError

    def send_summary(self, property_obj, ref_date, items) -> SunatResult:  # pragma: no cover
        raise NotImplementedError

    def send_voided(self, property_obj, ref_date, items) -> SunatResult:  # pragma: no cover
        raise NotImplementedError

    def send_despatch(self, guide) -> SunatResult:  # pragma: no cover
        raise NotImplementedError

    def get_status(self, ticket_number) -> SunatResult:  # pragma: no cover
        raise NotImplementedError


class SimulatorAdapter(SunatAdapter):
    """SUNAT interna: valida y responde como la real. Nada sale del sistema."""

    # -- utilidades -----------------------------------------------------------

    def _down(self, property_obj) -> bool:
        from .models import SimulationSettings

        return SimulationSettings.objects.filter(property=property_obj, connection_down=True).exists()

    def _offline(self):
        return SunatResult(False, "0100", msg("0100"), connection_error=True)

    def _today(self, property_obj):
        """El reloj de la SUNAT simulada es la fecha hotelera, así las prácticas son coherentes."""
        return property_obj.current_business_date()

    def _taxpayer(self, ruc):
        """Padrón: un RUC con dígito verificador válido existe y está ACTIVO/HABIDO salvo que el
        padrón ficticio diga otra cosa."""
        from .models import FakeTaxpayer

        t = FakeTaxpayer.objects.filter(ruc=ruc).first()
        return (t.status, t.condition) if t else ("ACTIVO", "HABIDO")

    def _cdr(self, prop, doc_id, receiver, code, text, notes=(), ticket=""):
        return ubl.cdr_xml(
            issuer_ruc=prop.ruc,
            doc_id=doc_id,
            receiver_doc=receiver,
            code=code,
            description=text,
            notes=notes,
            ticket=ticket,
        )

    # -- validación de comprobantes -------------------------------------------

    def validate(self, inv) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        """Devuelve (errores, observaciones) como pares (código, mensaje)."""
        from .models import SunatRegistry

        errors, obs = [], []
        prop = inv.property
        series = inv.series.code
        related = inv.related_invoice
        expected = "F" if inv.doc_type == "01" else "B" if inv.doc_type == "03" else None
        if inv.doc_type in ("07", "08") and related:
            expected = "F" if related.doc_type == "01" else "B"
        if expected and not series.startswith(expected):
            errors.append(("1001", msg("1001")))
        today = self._today(prop)
        if inv.issue_date > today + timedelta(days=1):
            errors.append(("2329", msg("2329")))
        if series.startswith("F") and (today - inv.issue_date).days > SEND_DAYS:
            errors.append(("2108", msg("2108")))
        # Receptor
        if series.startswith("F"):
            if inv.customer_doc_type != "6":
                errors.append(("2800", msg("2800")))
            elif not ruc_is_valid(inv.customer_doc):
                errors.append(("2017", msg("2017")))
            else:
                status, condition = self._taxpayer(inv.customer_doc)
                if status != "ACTIVO":
                    errors.append(("2020", msg("2020")))
                elif condition != "HABIDO":
                    obs.append(("4001", msg("4001")))
            if not inv.customer_address and inv.doc_type == "01":
                obs.append(("4095", msg("4095")))
        elif inv.customer_doc_type == "1" and not dni_is_valid(inv.customer_doc):
            errors.append(("2800", msg("2800")))
        # Montos
        lines = list(inv.lines.all())
        for i, ln in enumerate(lines, start=1):
            if ln.affectation == "10" and abs(ln.base * Decimal("0.18") - ln.igv) > Decimal("0.02"):
                errors.append(("3111", msg("3111", line=i)))
                break
            if ln.affectation == "40" and inv.customer_doc_type in ("1", "6"):
                errors.append(("2642", msg("2642")))
                break
        line_sum = sum((ln.total for ln in lines), Decimal("0"))
        if abs(line_sum - inv.prepaid_amount - inv.total) > Decimal("0.05"):
            errors.append(("3105", msg("3105")))
        # Notas: el comprobante modificado debe estar informado y vigente
        if inv.doc_type in ("07", "08"):
            if related is None:
                errors.append(("2524", msg("2524")))
            else:
                if related.doc_type not in ("01", "03") or related.series.code[0] != series[0]:
                    errors.append(("2116", msg("2116")))
                reg = (
                    SunatRegistry.objects.filter(
                        issuer_ruc=prop.ruc,
                        doc_type=related.doc_type,
                        series=related.series.code,
                        number=related.number,
                    )
                    .exclude(status=SunatRegistry.Status.VOIDED)
                    .first()
                )
                if reg is None:
                    errors.append(("2524", msg("2524")))
                elif inv.doc_type == "07":
                    others = [
                        n.hash for n in related.notes.filter(doc_type="07").exclude(pk=inv.pk) if n.hash
                    ]
                    credited = sum(
                        (
                            r.total
                            for r in SunatRegistry.objects.filter(
                                issuer_ruc=prop.ruc, doc_type="07", digest__in=others
                            ).exclude(status=SunatRegistry.Status.VOIDED)
                        ),
                        Decimal("0"),
                    )
                    if inv.total + credited > reg.total + Decimal("0.01"):
                        errors.append(("2525", msg("2525")))
        return errors, obs

    # -- envío síncrono (factura, boleta y notas) ----------------------------

    @transaction.atomic
    def send(self, invoice) -> SunatResult:
        from .models import SunatRegistry

        prop = invoice.property
        if self._down(prop):
            return self._offline()
        doc_id = invoice.full_number
        if ubl.digest_of(invoice.xml) != ubl.declared_digest(invoice.xml) or not invoice.xml:
            return SunatResult(False, "2335", msg("2335"))
        digest = ubl.declared_digest(invoice.xml)
        existing = SunatRegistry.objects.filter(
            issuer_ruc=prop.ruc, doc_type=invoice.doc_type, series=invoice.series.code, number=invoice.number
        ).first()
        if existing is not None:
            if existing.digest == digest:  # reenvío del mismo XML: SUNAT devuelve la misma constancia
                return SunatResult(
                    existing.status != "voided", "0", "Comprobante ya informado", cdr=existing.cdr_xml
                )
            return SunatResult(
                False,
                "1033",
                msg("1033"),
                cdr=self._cdr(prop, doc_id, invoice.customer_doc, "1033", msg("1033")),
            )
        errors, obs = self.validate(invoice)
        if errors:
            code, text = errors[0]
            return SunatResult(
                False, code, text, cdr=self._cdr(prop, doc_id, invoice.customer_doc, code, text)
            )
        text = msg("0", doc=invoice.get_doc_type_display(), id=doc_id)
        notes = [f"{c} - {t}" for c, t in obs]
        cdr = self._cdr(prop, doc_id, invoice.customer_doc, "0", text, notes)
        SunatRegistry.objects.create(
            issuer_ruc=prop.ruc,
            doc_type=invoice.doc_type,
            series=invoice.series.code,
            number=invoice.number,
            issue_date=invoice.issue_date,
            currency=invoice.currency,
            total=invoice.total,
            receiver_doc_type=invoice.customer_doc_type,
            receiver_doc=invoice.customer_doc,
            digest=digest,
            status=SunatRegistry.Status.OBSERVED if obs else SunatRegistry.Status.ACCEPTED,
            cdr_xml=cdr,
        )
        return SunatResult(True, "0", text, observations=notes, cdr=cdr)

    # -- envíos asíncronos con ticket -------------------------------------------

    def _ticket(self, prop, kind, file_name, xml, payload) -> SunatResult:
        from .models import SunatTicket

        if self._down(prop):
            return self._offline()
        seed = f"{prop.ruc}{kind}{file_name}{timezone.now().timestamp()}"
        number = str(int(hashlib.sha256(seed.encode()).hexdigest()[:13], 16))[:15]  # SUNAT: 15 dígitos
        delay = getattr(settings, "SUNAT_TICKET_SECONDS", 15)
        SunatTicket.objects.create(
            property=prop,
            kind=kind,
            number=number,
            file_name=file_name,
            xml=xml,
            payload=payload,
            ready_at=timezone.now() + timedelta(seconds=delay),
        )
        return SunatResult(
            True, "98", "Ticket generado: SUNAT procesará el envío", ticket=number, processing=True
        )

    def send_summary(self, property_obj, ref_date, items) -> SunatResult:
        file_id = self._file_id(property_obj, "RC")
        xml, _digest = ubl.summary_xml(property_obj, file_id, ref_date, items)
        return self._ticket(
            property_obj,
            "RC",
            f"{property_obj.ruc}-{file_id}",
            xml,
            {"ref_date": ref_date.isoformat(), "items": _jsonable(items)},
        )

    def send_voided(self, property_obj, ref_date, items) -> SunatResult:
        file_id = self._file_id(property_obj, "RA")
        xml, _digest = ubl.voided_xml(property_obj, file_id, ref_date, items)
        return self._ticket(
            property_obj,
            "RA",
            f"{property_obj.ruc}-{file_id}",
            xml,
            {"ref_date": ref_date.isoformat(), "items": _jsonable(items)},
        )

    def send_despatch(self, guide) -> SunatResult:
        return self._ticket(guide.property, "GRE", guide.file_name, guide.xml, {"guide": guide.pk})

    @staticmethod
    def _file_id(prop, prefix):
        from .models import SunatTicket

        today = timezone.localdate()
        n = SunatTicket.objects.filter(property=prop, kind=prefix, created_at__date=today).count() + 1
        return f"{prefix}-{today:%Y%m%d}-{n}"

    @transaction.atomic
    def get_status(self, ticket_number) -> SunatResult:
        from .models import SunatTicket

        t = SunatTicket.objects.select_for_update().filter(number=ticket_number).first()
        if t is None:
            return SunatResult(False, "0127", msg("0127"))
        if self._down(t.property):
            return self._offline()
        if t.status == SunatTicket.Status.PROCESSING:
            if timezone.now() < t.ready_at:
                return SunatResult(False, "98", "En proceso", ticket=t.number, processing=True)
            code, text = {
                "RC": self._process_summary,
                "RA": self._process_voided,
                "GRE": self._process_despatch,
            }[t.kind](t)
            t.status = SunatTicket.Status.DONE if code == "0" else SunatTicket.Status.ERROR
            t.response_code, t.response_message = code, text[:255]
            t.cdr_xml = self._cdr(t.property, t.file_name, "", code, text, ticket=t.number)
            t.processed_at = timezone.now()
            t.save()
        ok = t.status == SunatTicket.Status.DONE
        return SunatResult(ok, t.response_code, t.response_message, ticket=t.number, cdr=t.cdr_xml)

    def _process_voided(self, t) -> tuple[str, str]:
        from datetime import date

        from .models import SunatRegistry

        prop = t.property
        ref_date = date.fromisoformat(t.payload["ref_date"])
        today = self._today(prop)
        regs = []
        for it in t.payload["items"]:
            reg = SunatRegistry.objects.filter(
                issuer_ruc=prop.ruc, doc_type=it["doc_type"], series=it["series"], number=int(it["number"])
            ).first()
            if reg is None or reg.status == SunatRegistry.Status.VOIDED:
                return "2105", msg("2105")
            if (today - reg.issue_date).days > VOID_DAYS or (today - ref_date).days > VOID_DAYS:
                return "2375", msg("2375")
            regs.append(reg)
        for reg in regs:
            reg.status = SunatRegistry.Status.VOIDED
            reg.save(update_fields=["status"])
        return "0", f"La Comunicación de baja {t.file_name} ha sido aceptada"

    def _process_summary(self, t) -> tuple[str, str]:
        from datetime import date

        from .models import SunatRegistry

        prop = t.property
        ref_date = date.fromisoformat(t.payload["ref_date"])
        if (self._today(prop) - ref_date).days > VOID_DAYS:
            return "2375", msg("2375")
        for it in t.payload["items"]:
            series, number = it["number"].split("-")
            reg = SunatRegistry.objects.filter(
                issuer_ruc=prop.ruc, doc_type=it["doc_type"], series=series, number=int(number)
            ).first()
            if it["status"] == "1" and reg is None:
                SunatRegistry.objects.create(
                    issuer_ruc=prop.ruc,
                    doc_type=it["doc_type"],
                    series=series,
                    number=int(number),
                    issue_date=ref_date,
                    currency=it.get("currency", "PEN"),
                    total=Decimal(it["total"]),
                    receiver_doc_type=it.get("receiver_doc_type", ""),
                    receiver_doc=it["receiver_doc"],
                    digest=it["digest"],
                )
            if it["status"] == "3":
                if reg is None or reg.status == SunatRegistry.Status.VOIDED:
                    return "2105", msg("2105")
                reg.status = SunatRegistry.Status.VOIDED
                reg.save(update_fields=["status"])
        return "0", f"El Resumen diario {t.file_name} ha sido aceptado"

    def _process_despatch(self, t) -> tuple[str, str]:
        from .models import RemissionGuide, SunatRegistry

        guide = RemissionGuide.objects.select_related("property", "series").get(pk=t.payload["guide"])
        prop = guide.property
        if ubl.digest_of(guide.xml) != ubl.declared_digest(guide.xml):
            return "2335", msg("2335")
        lines = list(guide.lines.all())
        if guide.transport_mode == "01":
            if not ruc_is_valid(guide.carrier_ruc) or not guide.carrier_name.strip():
                return "3301", msg("3301")
        else:
            plate = guide.vehicle_plate.upper().replace(" ", "")
            if not PLATE.match(plate) or not dni_is_valid(guide.driver_doc) or not guide.driver_license:
                return "3302", msg("3302")
        if guide.transfer_date < guide.issue_date:
            return "3303", msg("3303")
        if guide.gross_weight <= 0 or not lines or any(ln.quantity <= 0 for ln in lines):
            return "3304", msg("3304")
        if not (
            re.fullmatch(r"\d{6}", guide.origin_ubigeo) and re.fullmatch(r"\d{6}", guide.destination_ubigeo)
        ):
            return "3305", msg("3305")
        if guide.reason == "04" and guide.recipient_doc != prop.ruc:
            return "3306", msg("3306")
        if guide.recipient_doc_type == "6" and not ruc_is_valid(guide.recipient_doc):
            return "2017", msg("2017")
        SunatRegistry.objects.update_or_create(
            issuer_ruc=prop.ruc,
            doc_type="09",
            series=guide.series.code,
            number=guide.number,
            defaults={
                "issue_date": guide.issue_date,
                "total": Decimal("0"),
                "digest": guide.hash,
                "receiver_doc_type": guide.recipient_doc_type,
                "receiver_doc": guide.recipient_doc,
            },
        )
        return "0", f"La Guía de remisión {guide.full_number} ha sido aceptada"


def _jsonable(items):
    return [{k: (str(v) if isinstance(v, Decimal) else v) for k, v in it.items()} for it in items]


class OSEAdapter(SunatAdapter):
    """Conexión real con un OSE/PSE. Se implementa al pasar a producción."""

    def send(self, invoice):
        raise NotImplementedError("Configure el OSE/PSE (Nubefact, Efact...) para SUNAT_MODE=production.")

    send_summary = send_voided = send_despatch = get_status = send


def get_adapter() -> SunatAdapter:
    return OSEAdapter() if settings.SUNAT_MODE == "production" else SimulatorAdapter()


def lookup_ruc(ruc: str):
    """Consulta RUC simulada contra el padrón local ficticio."""
    from .models import FakeTaxpayer

    return FakeTaxpayer.objects.filter(ruc=ruc).first()


def lookup_dni(dni: str):
    from .models import FakePerson

    return FakePerson.objects.filter(dni=dni).first()
