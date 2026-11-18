"""Yapılandırılmış (JSON) loglama.

Her log satırı tek bir JSON nesnesidir; Loki/Grafana'da `| json` ile alanlara ayrılır:
    {"ts": "...", "level": "info", "logger": "bilet_api.http", "msg": "request",
     "request_id": "...", "method": "GET", "path": "/events", "status": 200, "duration_ms": 12.3}

Kişisel veri (e-posta, isim, kart bilgisi) loglara YAZILMAZ; siparişler kodla izlenir.
"""

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# logging.LogRecord'un kendi alanları; bunlar dışındaki "extra" alanlar JSON'a eklenir.
_RESERVED = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if (rid := request_id_var.get()) is not None:
            data["request_id"] = rid
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                data[key] = value
        if record.exc_info:
            data["error"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False, default=str)


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # Uvicorn'un kendi erişim logu kapalı: her isteği aşağıdaki middleware tek satırda loglar.
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers[:] = []
        logging.getLogger(name).propagate = True


_http_log = logging.getLogger("bilet_api.http")
_QUIET_PATHS = {"/health"}  # Coolify sağlık kontrolü logları doldurmasın


class RequestLogMiddleware(BaseHTTPMiddleware):
    """Her istek için bir log satırı ve X-Request-ID başlığı."""

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if 8 <= len(incoming) <= 64 and incoming.isalnum() else uuid.uuid4().hex
        token = request_id_var.set(rid)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = rid
            return response
        except Exception:
            _http_log.exception("unhandled_error", extra={"method": request.method, "path": request.url.path})
            raise
        finally:
            duration = round((time.perf_counter() - start) * 1000, 1)
            if request.url.path not in _QUIET_PATHS or status >= 400:
                level = logging.ERROR if status >= 500 else logging.WARNING if status >= 400 else logging.INFO
                _http_log.log(
                    level,
                    "request",
                    extra={
                        "method": request.method,
                        "path": request.url.path,
                        "route": getattr(request.scope.get("route"), "path", None),
                        "status": status,
                        "duration_ms": duration,
                    },
                )
            request_id_var.reset(token)
