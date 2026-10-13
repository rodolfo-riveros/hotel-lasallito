from celery import shared_task


@shared_task
def push_channels_task(property_id):
    from apps.core.models import Property

    from .services import push_all

    return len(push_all(Property.objects.get(pk=property_id)))
