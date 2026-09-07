from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agents.base import AgentRegistry
from app.core.llm import LLMProvider
from app.core.storage import Storage
from app.deps import get_llm, get_registry, get_storage
from app.engine.persist import list_pipelines, load_pipeline, load_run, save_pipeline, save_run
from app.services.library import file_slots, package_session_pipeline, write_named_files
from app.services.dashboard import compile_dashboard, lineage_model
from app.services.explain import row_trace, sheet_rows
from app.services.ops import answer_run_question, library_card, missing_files, run_library_pipeline
from app.services.report import compile_report_spec, render_report, safe_filename, write_generated_report
from app.services.sessions import load_session, session_pipeline
from app.api.runs import _run_view

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


class SaveBody(BaseModel):
    session_id: str
    name: str
    version: str = "v1"


class PreviewBody(BaseModel):
    session_id: str
    extra: dict = Field(default_factory=dict)


class AskBody(BaseModel):
    question: str
    run_id: str
    view: str | None = None
    node_id: str | None = None
    port: str | None = None
    row_index: int | None = None


class ReportBody(BaseModel):
    format: str = "xlsx"
    sections: list[dict] | None = None


class ExplainRowBody(BaseModel):
    node_id: str
    port: str
    row_index: int


def _session(storage: Storage, session_id: str):
    try:
        return load_session(storage, session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc


def _pipeline(storage: Storage, pipeline_id: str):
    try:
        return load_pipeline(storage, pipeline_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="pipeline not found") from exc


@router.get("")
def get_pipelines(storage: Storage = Depends(get_storage)) -> dict:
    items = list_pipelines(storage)
    return {"pipelines": [library_card(p) for p in items]}


@router.get("/{pipeline_id}")
def get_pipeline(pipeline_id: str, storage: Storage = Depends(get_storage)) -> dict:
    pipeline = _pipeline(storage, pipeline_id)
    body = pipeline.model_dump(mode="json")
    body["file_slots"] = file_slots(pipeline)
    body["missing_files"] = missing_files(storage, pipeline)
    return body


@router.post("", status_code=status.HTTP_201_CREATED)
def save_to_library(body: SaveBody, storage: Storage = Depends(get_storage)) -> dict:
    session = _session(storage, body.session_id)
    if not session.confirmed:
        raise HTTPException(status_code=400, detail="session is not confirmed")
    draft = session_pipeline(session)
    if not draft.nodes:
        raise HTTPException(status_code=400, detail="session has no draft DAG")
    pipeline = package_session_pipeline(storage, session, body.name, body.version)
    save_pipeline(storage, pipeline)
    return pipeline.model_dump(mode="json")


@router.post("/preview")
def preview_pipeline(body: PreviewBody, storage: Storage = Depends(get_storage)) -> dict:
    session = _session(storage, body.session_id)
    pipeline = session_pipeline(session)
    return {"session_id": session.id, "confirmed": session.confirmed, "pipeline": pipeline.model_dump(mode="json")}


@router.post("/{pipeline_id}/files")
async def upload_library_files(
    pipeline_id: str,
    files: list[UploadFile] = File(),
    storage: Storage = Depends(get_storage),
) -> dict:
    pipeline = _pipeline(storage, pipeline_id)
    if not files:
        raise HTTPException(status_code=400, detail="files are required")
    blobs: list[tuple[str, bytes]] = []
    for item in files:
        blobs.append((item.filename or "upload.bin", await item.read()))
    try:
        written = write_named_files(storage, pipeline, blobs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "written": written,
        "file_slots": file_slots(pipeline),
        "missing_files": missing_files(storage, pipeline),
    }


@router.post("/{pipeline_id}/run")
async def run_saved_pipeline(
    pipeline_id: str,
    storage: Storage = Depends(get_storage),
    llm: LLMProvider = Depends(get_llm),
    registry: AgentRegistry = Depends(get_registry),
) -> dict:
    pipeline = _pipeline(storage, pipeline_id)
    try:
        run = await run_library_pipeline(storage, llm, registry, pipeline)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _run_view(run)


@router.post("/{pipeline_id}/run/stream")
async def stream_saved_pipeline(
    pipeline_id: str,
    storage: Storage = Depends(get_storage),
    llm: LLMProvider = Depends(get_llm),
    registry: AgentRegistry = Depends(get_registry),
):
    pipeline = _pipeline(storage, pipeline_id)
    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def on_event(event: dict) -> None:
        await queue.put(event)

    async def work() -> None:
        try:
            run = await run_library_pipeline(storage, llm, registry, pipeline, on_event=on_event)
            await queue.put({"type": "result", "run": _run_view(run)})
        except ValueError as exc:
            await queue.put({"type": "error", "message": str(exc)})
        except Exception as exc:
            await queue.put({"type": "error", "message": str(exc)})
        finally:
            await queue.put(None)

    async def generate():
        task = asyncio.create_task(work())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield f"data: {json.dumps(item, default=str)}\n\n"
        finally:
            await task

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{pipeline_id}/ask")
async def ask_saved_pipeline(
    pipeline_id: str,
    body: AskBody,
    storage: Storage = Depends(get_storage),
    llm: LLMProvider = Depends(get_llm),
) -> dict:
    pipeline = _pipeline(storage, pipeline_id)
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="question is required")
    try:
        answer = await answer_run_question(
            llm,
            pipeline,
            body.run_id,
            storage,
            body.question.strip(),
            view=body.view,
            node_id=body.node_id,
            port=body.port,
            row_index=body.row_index,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    return {"answer": answer, "run_id": body.run_id}


@router.get("/{pipeline_id}/runs/{run_id}/dashboard")
async def get_run_dashboard(
    pipeline_id: str,
    run_id: str,
    storage: Storage = Depends(get_storage),
    llm: LLMProvider = Depends(get_llm),
) -> dict:
    pipeline = _pipeline(storage, pipeline_id)
    try:
        run = load_run(storage, run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    if run.pipeline_id != pipeline_id:
        raise HTTPException(status_code=404, detail="run not found")
    return await compile_dashboard(run, llm, pipeline)


@router.get("/{pipeline_id}/runs/{run_id}/lineage")
def get_run_lineage(
    pipeline_id: str,
    run_id: str,
    storage: Storage = Depends(get_storage),
) -> dict:
    pipeline = _pipeline(storage, pipeline_id)
    try:
        run = load_run(storage, run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    if run.pipeline_id != pipeline_id:
        raise HTTPException(status_code=404, detail="run not found")
    return lineage_model(pipeline, run)


def _load_run(storage: Storage, pipeline_id: str, run_id: str):
    pipeline = _pipeline(storage, pipeline_id)
    try:
        run = load_run(storage, run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    if run.pipeline_id != pipeline_id:
        raise HTTPException(status_code=404, detail="run not found")
    return pipeline, run


@router.get("/{pipeline_id}/runs/{run_id}/sheets/{node_id}/{port}/rows")
def get_sheet_rows(
    pipeline_id: str,
    run_id: str,
    node_id: str,
    port: str,
    offset: int = 0,
    limit: int = 50,
    only_exceptions: bool = False,
    storage: Storage = Depends(get_storage),
) -> dict:
    _load_run(storage, pipeline_id, run_id)
    return sheet_rows(
        load_run(storage, run_id),
        node_id,
        port,
        offset=max(offset, 0),
        limit=limit,
        only_exceptions=only_exceptions,
    )


@router.post("/{pipeline_id}/runs/{run_id}/explain/row")
def post_explain_row(
    pipeline_id: str,
    run_id: str,
    body: ExplainRowBody,
    storage: Storage = Depends(get_storage),
) -> dict:
    pipeline, run = _load_run(storage, pipeline_id, run_id)
    return row_trace(pipeline, run, body.node_id, body.port, body.row_index)


@router.get("/{pipeline_id}/runs/{run_id}/report/spec")
async def get_report_spec(
    pipeline_id: str,
    run_id: str,
    fmt: str = "xlsx",
    storage: Storage = Depends(get_storage),
    llm: LLMProvider = Depends(get_llm),
) -> dict:
    pipeline, run = _load_run(storage, pipeline_id, run_id)
    kind = "pdf" if fmt == "pdf" else "xlsx"
    return await compile_report_spec(pipeline, run, kind, llm)


@router.post("/{pipeline_id}/runs/{run_id}/report")
async def post_report(
    pipeline_id: str,
    run_id: str,
    body: ReportBody,
    storage: Storage = Depends(get_storage),
    llm: LLMProvider = Depends(get_llm),
) -> dict:
    pipeline, run = _load_run(storage, pipeline_id, run_id)
    fmt = "pdf" if body.format == "pdf" else "xlsx"
    spec = await compile_report_spec(pipeline, run, fmt, llm)
    if body.sections:
        spec = {**spec, "sections": [item for item in body.sections if item.get("catalog_id")]}
    data = render_report(spec, pipeline, run, fmt)
    filename = safe_filename(f"{pipeline.name or 'report'}_{run.id[:8]}", fmt)
    path = write_generated_report(storage, run, data, filename)
    save_run(storage, run)
    return {"artifact": filename, "path": path, "format": fmt}
