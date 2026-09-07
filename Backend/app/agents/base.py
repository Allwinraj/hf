from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.llm import LLMProvider
from app.core.storage import Storage
from app.models.envelope import Envelope
from app.models.knowledge import SessionKnowledge
from app.models.pipeline import Node


@dataclass
class RunContext:
    """Per-run handle. knowledge_store is filled by Phase 3A."""

    run_id: str
    llm: LLMProvider
    storage: Storage
    logger: logging.Logger
    knowledge_store: SessionKnowledge | None = None
    inputs: list[Envelope] = field(default_factory=list)
    node: Node | None = None


class Agent(Protocol):
    name: str

    async def execute(self, ctx: RunContext, env: Envelope) -> list[Envelope]: ...


class AgentRegistry:
    def __init__(self) -> None:
        self._classes: dict[str, type[Agent]] = {}

    def register(self, agent_cls: type[Agent]) -> type[Agent]:
        name = getattr(agent_cls, "name", None)
        if not name:
            raise ValueError(f"{agent_cls!r} is missing a class attribute 'name'")
        self._classes[name] = agent_cls
        return agent_cls

    def get(self, name: str) -> type[Agent]:
        try:
            return self._classes[name]
        except KeyError as exc:
            raise KeyError(f"unknown agent {name!r}") from exc

    def create(self, name: str) -> Agent:
        return self._classes[name]()  # type: ignore[call-arg]

    def names(self) -> list[str]:
        return sorted(self._classes)


registry = AgentRegistry()
