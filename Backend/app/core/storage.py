from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml


class Storage:
    """Atomic JSON/YAML filesystem store. Swap-in seam for a later database."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)

    def read_json(self, *parts: str) -> Any:
        return json.loads(self.path(*parts).read_text(encoding="utf-8"))

    def write_json(self, data: Any, *parts: str) -> Path:
        target = self.path(*parts)
        payload = json.dumps(data, indent=2, default=str)
        self._atomic_write(target, payload)
        return target

    def read_yaml(self, *parts: str) -> Any:
        return yaml.safe_load(self.path(*parts).read_text(encoding="utf-8"))

    def write_yaml(self, data: Any, *parts: str) -> Path:
        target = self.path(*parts)
        payload = yaml.safe_dump(data, sort_keys=False)
        self._atomic_write(target, payload)
        return target

    def list(self, *parts: str) -> list[Path]:
        directory = self.path(*parts)
        if not directory.exists():
            return []
        return sorted(p for p in directory.iterdir() if p.is_file())

    def delete(self, *parts: str) -> None:
        target = self.path(*parts)
        if target.exists():
            target.unlink()

    def exists(self, *parts: str) -> bool:
        return self.path(*parts).exists()

    def write_bytes(self, data: bytes, *parts: str) -> Path:
        target = self.path(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=str(target.parent),
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
            return target
        except Exception:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise

    def _atomic_write(self, target: Path, payload: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=str(target.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
        except Exception:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise
