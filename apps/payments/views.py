from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .gateways import TestGateway
from .models import OnlinePayment
from .services import complete


@require_http_methods(["GET", "POST"])
def test_checkout(request, token):
    """Página de pago alojada de la pasarela de prueba (simula Izipay/Niubiz/Culqi).

    La tarjeta se ingresa aquí, "en la pasarela"; el PMS solo recibe el resultado.
    """
    payment = get_object_or_404(OnlinePayment, token=token)
    error = ""
    if request.method == "POST" and payment.status == OnlinePayment.Status.CREATED:
        if request.POST.get("cancel"):
            payment.status = OnlinePayment.Status.CANCELLED
            payment.save(update_fields=["status"])
        else:
            result = TestGateway().charge(request.POST.get("card", ""))
            payment = complete(payment, result)
            error = payment.error
        if payment.status != OnlinePayment.Status.FAILED and payment.return_url:
            return redirect(payment.return_url)
    return render(request, "payments/test_checkout.html", {"p": payment, "error": error})
