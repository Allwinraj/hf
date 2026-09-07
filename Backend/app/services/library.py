from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from app.core.logging import new_id
from app.core.storage import Storage
from app.models.chat import InterviewSession
from app.models.pipeline import Pipeline
from app.services.sessions import session_pipeline


def package_session_pipeline(
    storage: Storage,
    session: InterviewSession,
    name: str,
    version: str,
) -> Pipeline:
    draft = session_pipeline(session)
    pid = new_id()
    nodes = []
    slots: list[dict[str, Any]] = []
    for node in draft.nodes:
        cfg = dict(node.config or {})
        mode = node.mode or cfg.get("mode")
        if node.agent == "ingestion" and cfg.get("path"):
            src = Path(str(cfg["path"]))
            filename = str(cfg.get("filename") or src.name)
            dest = storage.path("pipelines", pid, "files", filename)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.exists():
                shutil.copy2(src, dest)
            cfg["path"] = str(dest)
            cfg["filename"] = filename
            if mode == "knowledge":
                cfg["session_id"] = pid
            slots.append(
                {
                    "node_id": node.id,
                    "kind": "knowledge" if mode == "knowledge" else "data",
                    "filename": filename,
                    "label": node.label or filename,
                }
            )
        nodes.append(node.model_copy(update={"config": cfg}))
    if storage.exists("knowledge", f"{session.id}.json"):
        src_k = storage.path("knowledge", f"{session.id}.json")
        dest_k = storage.path("knowledge", f"{pid}.json")
        dest_k.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_k, dest_k)
    return Pipeline(
        id=pid,
        name=name,
        version=version,
        nodes=nodes,
        edges=list(draft.edges),
        meta={
            "file_slots": slots,
            "brief": session.extra.get("pipeline_brief") or session.summary,
            "purpose": session.extra.get("description"),
            "source_session_id": session.id,
        },
    )


def file_slots(pipeline: Pipeline) -> list[dict[str, Any]]:
    slots = list((pipeline.meta or {}).get("file_slots") or [])
    if slots:
        return slots
    inferred = []
    for node in pipeline.nodes:
        if node.agent != "ingestion":
            continue
        cfg = node.config or {}
        filename = str(cfg.get("filename") or Path(str(cfg.get("path") or "")).name)
        if not filename:
            continue
        inferred.append(
            {
                "node_id": node.id,
                "kind": "knowledge" if (node.mode or cfg.get("mode")) == "knowledge" else "data",
                "filename": filename,
                "label": node.label or filename,
            }
        )
    return inferred


def slot_path(storage: Storage, pipeline: Pipeline, filename: str) -> Path:
    return storage.path("pipelines", pipeline.id, "files", filename)


def write_named_files(
    storage: Storage,
    pipeline: Pipeline,
    files: list[tuple[str, bytes]],
) -> list[str]:
    allowed = {s["filename"].lower(): s["filename"] for s in file_slots(pipeline)}
    if not allowed:
        raise ValueError("this pipeline has no file slots")
    written: list[str] = []
    unknown: list[str] = []
    for name, blob in files:
        key = Path(name).name
        match = allowed.get(key.lower())
        if not match:
            unknown.append(key)
            continue
        dest = slot_path(storage, pipeline, match)
        dest.parent.mkdir(parents=True, exist_ok=True)
        storage.write_bytes(blob, "pipelines", pipeline.id, "files", match)
        written.append(match)
    if unknown:
        expect = ", ".join(sorted(allowed.values()))
        raise ValueError(
            f"File names must match the original slots ({expect}). "
            f"Unknown: {', '.join(unknown)}"
        )
    if not written:
        raise ValueError("no matching files were uploaded")
    return written
