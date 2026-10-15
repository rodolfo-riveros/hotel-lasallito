"""Envío programado de reportes por correo al gerente (RF-REP-06). Lo llama `run_scheduler`."""

from datetime import date, timedelta
from types import SimpleNamespace

from django.utils.translation import gettext as _

from .models import ReportSubscription


def period(frequency: str, today: date) -> tuple[date, date] | None:
    """Periodo a reportar si hoy toca enviar; None si no corresponde."""
    if frequency == ReportSubscription.Frequency.DAILY:
        return today - timedelta(days=1), today
    if frequency == ReportSubscription.Frequency.WEEKLY and today.weekday() == 0:
        return today - timedelta(days=7), today
    if frequency == ReportSubscription.Frequency.MONTHLY and today.day == 1:
        return (today - timedelta(days=1)).replace(day=1), today
    return None


def render_attachment(sub: ReportSubscription, start: date, end: date):
    from .exports import export_table
    from .views import REPORTS, build

    fake = SimpleNamespace(property=sub.property, GET={"start": start.isoformat(), "end": end.isoformat()})
    header, rows, _extra = build(fake, sub.report)
    title = (
        f"{REPORTS[sub.report]} · {sub.property.name} · {start:%d/%m/%Y}–{(end - timedelta(days=1)):%d/%m/%Y}"
    )
    resp = export_table(title, header, rows, sub.format, filename=f"{sub.report}-{start:%Y%m%d}")
    mimetype = resp["Content-Type"].split(";")[0]
    return title, (f"{sub.report}-{start:%Y%m%d}.{sub.format}", resp.content, mimetype)


def send_subscription(sub: ReportSubscription, today: date, force=False) -> int:
    from apps.comms.services import send_message

    rng = (today - timedelta(days=1), today) if force else period(sub.frequency, today)
    if rng is None or (sub.last_sent_on == today and not force):
        return 0
    title, attachment = render_attachment(sub, *rng)
    body = _(
        "Adjunto: %(t)s.\n\nEnvío automático del PMS. Para dejar de recibirlo, pida al administrador que "
        "desactive este envío."
    ) % {"t": title}
    for email in sub.emails:
        send_message(sub.property, "email", email, title, body, attachments=[attachment])
    ReportSubscription.objects.filter(pk=sub.pk).update(last_sent_on=today)
    return len(sub.emails)


def send_due(property_obj, today: date | None = None) -> int:
    today = today or property_obj.current_business_date()
    return sum(
        send_subscription(s, today)
        for s in ReportSubscription.objects.filter(property=property_obj, is_active=True)
    )
