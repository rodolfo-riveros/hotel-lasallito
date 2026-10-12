from .request_context import RequestInfo, reset_request_info, set_request_info


def client_ip(request) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


class RequestContextMiddleware:
    """Guarda usuario, IP y navegador de la petición para la auditoría."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = set_request_info(
            RequestInfo(
                user=getattr(request, "user", None),
                ip_address=client_ip(request),
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:255],
            )
        )
        try:
            return self.get_response(request)
        finally:
            reset_request_info(token)
