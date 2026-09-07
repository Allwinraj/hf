from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

EnvelopePort = Literal[
    "default",
    "matched",
    "residuals",
    "exceptions",
    "approved",
    "flagged",
    "escalated",
]


class Envelope(BaseModel):
    """Universal A2A message between agents."""

    run_id: str
    node_id: str
    port: EnvelopePort = "default"
    payload: dict[str, Any] = Field(default_factory=dict)
    knowledge_context: dict[str, Any] | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    schema_ref: str | None = None
    emitted_by: str
