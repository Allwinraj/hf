from __future__ import annotations

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
run_id_var: ContextVar[str | None] = ContextVar("run_id", default=None)
correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def new_id() -> str:
    return uuid.uuid4().hex


def bind_request(request_id: str | None = None) -> str:
    rid = request_id or new_id()
    request_id_var.set(rid)
    if correlation_id_var.get() is None:
        correlation_id_var.set(rid)
    return rid


def bind_run(run_id: str) -> None:
    run_id_var.set(run_id)
    correlation_id_var.set(run_id)


def clear_context() -> None:
    request_id_var.set(None)
    run_id_var.set(None)
    correlation_id_var.set(None)


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "correlation_id": correlation_id_var.get(),
            "request_id": request_id_var.get(),
            "run_id": run_id_var.get(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    plain = logging.StreamHandler(sys.stdout)
    plain.setFormatter(logging.Formatter("%(asctime)s [NEXUS] %(message)s", datefmt="%H:%M:%S"))
    for name in ("nexus.interview", "nexus.runner"):
        named = logging.getLogger(name)
        named.handlers.clear()
        named.setLevel(logging.DEBUG)
        named.addHandler(plain)
        named.propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
