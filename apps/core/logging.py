"""Registros estructurados en JSON (RNF-MAN-05).

Con `LOG_FORMAT=json` cada línea es un objeto JSON con hora, nivel, módulo, mensaje y el
contexto de la petición (usuario, propiedad e IP), listo para Better Stack, Grafana Loki,
CloudWatch o similar. Los errores se envían además a Sentry si se define `SENTRY_DSN`.
"""

import json
import logging
from datetime import UTC, datetime


class RequestContextFilter(logging.Filter):
    def filter(self, record):
        from .request_context import get_request_info

        info = get_request_info()
        user = info.user
        record.pms_user = getattr(user, "username", "") if getattr(user, "is_authenticated", False) else ""
        record.pms_property = info.property_id
        record.pms_ip = info.ip_address or ""
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record):
        data = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "user": getattr(record, "pms_user", ""),
            "property": getattr(record, "pms_property", None),
            "ip": getattr(record, "pms_ip", ""),
        }
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False, default=str)
