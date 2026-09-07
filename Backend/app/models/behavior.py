from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.core.storage import Storage


class AgentBehavior(BaseModel):
    name: str
    version: str
    modes: list[str] = Field(default_factory=list)
    prompts: dict[str, str] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)


class BehaviorVersion(BaseModel):
    """On-disk unit: data/agents/<name>/<version>.yaml"""

    behavior: AgentBehavior

    @property
    def ref(self) -> str:
        return f"{self.behavior.name}@{self.behavior.version}"


def load_behavior(storage: Storage, name: str, version: str) -> BehaviorVersion:
    data = storage.read_yaml("agents", name, f"{version}.yaml")
    return BehaviorVersion(behavior=AgentBehavior.model_validate(data))


def load_behavior_file(path: Path) -> BehaviorVersion:
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return BehaviorVersion(behavior=AgentBehavior.model_validate(data))
