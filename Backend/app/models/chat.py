from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.pipeline import Edge, Node

SessionStatus = Literal[
    "welcome",
    "collecting",
    "interview",
    "ready_to_confirm",
    "confirmed",
    "handoff",
]


class ChatMessage(BaseModel):
    id: str
    role: Literal["assistant", "user", "system"]
    content: str
    meta: dict[str, Any] = Field(default_factory=dict)


class ExtractedRequirement(BaseModel):
    id: str
    kind: str
    value: dict[str, Any] = Field(default_factory=dict)
    source_message_id: str | None = None


class ConfigPatch(BaseModel):
    node_id: str
    config: dict[str, Any] = Field(default_factory=dict)


class ProgressiveReveal(BaseModel):
    upsert_nodes: list[Node] = Field(default_factory=list)
    remove_node_ids: list[str] = Field(default_factory=list)
    upsert_edges: list[Edge] = Field(default_factory=list)
    remove_edge_ids: list[str] = Field(default_factory=list)
    config_patches: list[ConfigPatch] = Field(default_factory=list)


class InterviewSession(BaseModel):
    """Created empty; files and DAG arrive later (Phase 4)."""

    id: str
    status: SessionStatus = "welcome"
    confirmed: bool = False
    messages: list[ChatMessage] = Field(default_factory=list)
    requirements: list[ExtractedRequirement] = Field(default_factory=list)
    pipeline: dict[str, Any] | None = None
    uploads: list[dict[str, Any]] = Field(default_factory=list)
    question_count: int = 0
    summary: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
