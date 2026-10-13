"""Cada cambio de inventario marca la propiedad para publicar en los canales (RF-CHA-02, RNF-REN-03)."""

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver


def _changed(property_obj):
    from .services import mark_dirty

    mark_dirty(property_obj)
    if getattr(settings, "CHANNEL_SYNC_ASYNC", False):
        # Con Redis y un worker de Celery se publica en segundos (RNF-REN-03).
        from .tasks import push_channels_task

        transaction.on_commit(lambda: push_channels_task.delay(property_obj.pk))


@receiver(post_save, sender="reservations.Reservation", dispatch_uid="channels_res_changed")
def reservation_changed(sender, instance, **kwargs):
    _changed(instance.property)


@receiver(post_save, sender="rooms.RoomBlock", dispatch_uid="channels_block_changed")
def block_changed(sender, instance, **kwargs):
    _changed(instance.property)
