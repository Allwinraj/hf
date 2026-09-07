from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.envelope import Envelope

RunStatus = Literal["queued", "running", "completed", "failed_with_exceptions"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RunStep(BaseModel):
    node_id: str
    agent: str
    behavior_version: str = ""
    status: Literal["ok", "skipped", "error"] = "ok"
    inputs: list[Envelope] = Field(default_factory=list)
    outputs: list[Envelope] = Field(default_factory=list)
    duration_ms: float = 0.0
    error: str | None = None
    skip_reason: str | None = None
    summary: str = ""


class Run(BaseModel):
    id: str
    pipeline_id: str
    pipeline_version: str = "0.1"
    status: RunStatus = "queued"
    steps: list[RunStep] = Field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    artifacts: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)

    def mark_running(self) -> None:
        self.status = "running"
        self.started_at = _now()

    def mark_done(self, *, failed: bool) -> None:
        self.finished_at = _now()
        self.status = "failed_with_exceptions" if failed else "completed"
