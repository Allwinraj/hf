from __future__ import annotations

from typing import Any

from app.engine.ast_sandbox import eval_expr
from app.models.envelope import Envelope
from app.models.pipeline import Edge


def _flatten(payload: dict[str, Any]) -> dict[str, Any]:
    names = dict(payload)
    nested = payload.get("record")
    if isinstance(nested, dict):
        names.update(nested)
    return names


def edge_accepts(edge: Edge, envelope: Envelope) -> bool:
    if envelope.port != edge.source_port:
        return False
    if edge.type != "conditional" or not edge.condition:
        return True
    names = _flatten(envelope.payload)
    names["port"] = envelope.port
    return bool(eval_expr(edge.condition, names))
