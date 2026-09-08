from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.agents.base import AgentRegistry
from app.core.llm import LLMProvider
from app.core.storage import Storage
from app.deps import get_llm, get_registry, get_storage
from app.engine.persist import load_pipeline, load_run, save_run
from app.engine.runner import PipelineRunner
from app.services.knowledge import load_knowledge
from app.services.mail import apply_mail_actions, save_mail_draft
from app.services.sap_po import apply_sap_posts
from app.services.sessions import load_session, session_pipeline

router = APIRouter(prefix="/runs", tags=["runs"])


class RunBody(BaseModel):
    session_id: str | None = None
    pipeline_id: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)


class MailSendBody(BaseModel):
    action: str
    mail_ids: list[str] = Field(default_factory=list)


class MailDraftBody(BaseModel):
    mail_id: str
    to_address: str | None = None
    draft_subject: str | None = None
    draft_body: str | None = None
    qty: int | float | str | None = None
    budget: int | float | str | None = None
    item: str | None = None


class MailSapBody(BaseModel):
    mail_ids: list[str] = Field(default_factory=list)
    post_all: bool = False


@router.post("")
async def start_run(
    body: RunBody,
    storage: Storage = Depends(get_storage),
    llm: LLMProvider = Depends(get_llm),
    registry: AgentRegistry = Depends(get_registry),
) -> dict:
    if not body.session_id and not body.pipeline_id:
        raise HTTPException(status_code=400, detail="session_id or pipeline_id is required")
    knowledge = None
    extra: dict[str, Any] = {}
    if body.session_id:
        try:
            session = load_session(storage, body.session_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc
        if not session.confirmed:
            raise HTTPException(status_code=400, detail="session is not confirmed")
        pipeline = session_pipeline(session)
        extra["session_id"] = session.id
        extra["source"] = "session"
        if storage.exists("knowledge", f"{session.id}.json"):
            knowledge = load_knowledge(storage, session.id)
    else:
        try:
            pipeline = load_pipeline(storage, body.pipeline_id or "")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="pipeline not found") from exc
        extra["pipeline_id"] = pipeline.id
        extra["source"] = "library"
    if not pipeline.nodes:
        raise HTTPException(status_code=400, detail="pipeline has no nodes")
    runner = PipelineRunner(registry, storage, llm)
    run = await runner.run(pipeline, knowledge=knowledge, seed=body.inputs or None)
    run.extra.update(extra)
    save_run(storage, run)
    return _run_view(run)


@router.get("/{run_id}")
def get_run(run_id: str, storage: Storage = Depends(get_storage)) -> dict:
    run = _load(storage, run_id)
    return _run_view(run)


@router.post("/{run_id}/mail/send")
def send_mail(
    run_id: str,
    body: MailSendBody,
    storage: Storage = Depends(get_storage),
) -> dict:
    action = (body.action or "").strip().lower()
    if action not in {"send", "skip", "send_all"}:
        raise HTTPException(status_code=400, detail="action must be send, skip, or send_all")
    run = _load(storage, run_id)
    pipeline = _pipeline_for_run(storage, run)
    try:
        rows = apply_mail_actions(run, pipeline, action=action, mail_ids=body.mail_ids)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"mail send failed: {exc}") from exc
    save_run(storage, run)
    return {"ok": True, "action": action, "rows": rows}


@router.post("/{run_id}/mail/draft")
def save_draft(
    run_id: str,
    body: MailDraftBody,
    storage: Storage = Depends(get_storage),
) -> dict:
    run = _load(storage, run_id)
    try:
        row = save_mail_draft(
            run,
            body.mail_id,
            to_address=body.to_address,
            draft_subject=body.draft_subject,
            draft_body=body.draft_body,
            qty=body.qty,
            budget=body.budget,
            item=body.item,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    save_run(storage, run)
    return {"ok": True, "row": row}


@router.post("/{run_id}/mail/sap")
def post_sap(
    run_id: str,
    body: MailSapBody,
    storage: Storage = Depends(get_storage),
) -> dict:
    run = _load(storage, run_id)
    try:
        posted = apply_sap_posts(run, mail_ids=body.mail_ids, post_all=body.post_all)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"SAP post failed: {exc}") from exc
    save_run(storage, run)
    return {"ok": posted.get("ok", False), **posted}


def _pipeline_for_run(storage: Storage, run):
    pid = run.pipeline_id
    if storage.exists("pipelines", f"{pid}.json"):
        return load_pipeline(storage, pid)
    sid = (run.extra or {}).get("session_id")
    if sid:
        session = load_session(storage, sid)
        return session_pipeline(session)
    raise HTTPException(status_code=404, detail="pipeline not found")


@router.get("/{run_id}/snapshot")
def get_snapshot(run_id: str, storage: Storage = Depends(get_storage)) -> dict:
    run = _load(storage, run_id)
    pipeline = None
    pid = run.pipeline_id
    if storage.exists("pipelines", f"{pid}.json"):
        pipeline = load_pipeline(storage, pid).model_dump(mode="json")
    elif run.extra.get("session_id"):
        try:
            session = load_session(storage, run.extra["session_id"])
            pipeline = session_pipeline(session).model_dump(mode="json")
        except FileNotFoundError:
            pipeline = None
    return {"run": run.model_dump(mode="json"), "pipeline": pipeline}


@router.get("/{run_id}/artifacts/{name}")
def get_artifact(run_id: str, name: str, storage: Storage = Depends(get_storage)):
    _load(storage, run_id)
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(status_code=400, detail="invalid artifact name")
    path = storage.path("runs", run_id, "artifacts", name)
    if not path.exists():
        raise HTTPException(status_code=404, detail="artifact not found")
    media = "application/pdf" if path.suffix.lower() == ".pdf" else (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if path.suffix.lower() == ".xlsx"
        else "application/octet-stream"
    )
    return FileResponse(path, filename=name, media_type=media)


def _load(storage: Storage, run_id: str):
    try:
        return load_run(storage, run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc


def _run_view(run) -> dict:
    steps = []
    for step in run.steps:
        emitted = [env.emitted_by for env in step.outputs]
        steps.append(
            {
                "node_id": step.node_id,
                "agent": step.agent,
                "behavior_version": step.behavior_version,
                "status": step.status,
                "duration_ms": step.duration_ms,
                "error": step.error,
                "skip_reason": step.skip_reason,
                "summary": step.summary,
                "emitted_by": emitted,
                "output_ports": [env.port for env in step.outputs],
            }
        )
    return {
        "id": run.id,
        "pipeline_id": run.pipeline_id,
        "pipeline_version": run.pipeline_version,
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "error": run.error,
        "artifacts": [Path(a).name for a in run.artifacts],
        "artifact_paths": run.artifacts,
        "steps": steps,
        "extra": run.extra,
    }
