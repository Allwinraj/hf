from __future__ import annotations

import yaml

from app.core.settings import BACKEND_ROOT
from app.core.storage import Storage
from app.models.behavior import AgentBehavior, BehaviorVersion

PACKAGED_AGENTS = BACKEND_ROOT / "data" / "agents"


def list_behavior_versions(storage: Storage, name: str) -> list[BehaviorVersion]:
    found: dict[str, BehaviorVersion] = {}
    for directory in (PACKAGED_AGENTS / name, storage.path("agents", name)):
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            behavior = AgentBehavior.model_validate(data)
            found[behavior.version] = BehaviorVersion(behavior=behavior)
    return [found[key] for key in sorted(found)]
