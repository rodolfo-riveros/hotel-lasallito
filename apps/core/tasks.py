"""Tareas Celery (RNF-REN-04). Con Redis disponible, Celery beat llama `run_scheduler_task`."""

from celery import shared_task


@shared_task
def run_scheduler_task():
    from apps.core.models import Property
    from apps.core.scheduler import run_all

    return {p.code: run_all(p) for p in Property.objects.filter(is_active=True)}
