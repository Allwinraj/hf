from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.core.llm import LLMProvider
from app.core.storage import Storage
from app.deps import get_llm, get_storage
from app.services.interview import (
    bootstrap_session,
    confirm_session,
    handle_message,
    handle_upload,
    handoff_session,
    sync_node_async,
)
from app.services.parser import ParseError
from app.services.sessions import load_session

router = APIRouter(prefix="/chat", tags=["chat"])


class MessageBody(BaseModel):
    session_id: str
    content: str


class ConfirmBody(BaseModel):
    session_id: str


class HandoffBody(BaseModel):
    session_id: str


class SyncNodeBody(BaseModel):
    session_id: str
    node_id: str
    config: dict = Field(default_factory=dict)


def _session_or_404(storage: Storage, session_id: str):
    try:
        return load_session(storage, session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc


@router.post("/session")
async def post_session(
    storage: Storage = Depends(get_storage),
    llm: LLMProvider = Depends(get_llm),
) -> dict:
    session = await bootstrap_session(storage, llm)
    return {
        "session_id": session.id,
        "status": session.status,
        "confirmed": session.confirmed,
        "question_count": session.question_count,
        "ready_to_confirm": False,
        "summary": None,
        "upload_offer": session.extra.get("upload_offer"),
        "message": session.messages[0].model_dump(mode="json"),
        "reveal": None,
        "pipeline": session.pipeline,
    }


@router.post("/message")
async def post_message(
    body: MessageBody,
    storage: Storage = Depends(get_storage),
    llm: LLMProvider = Depends(get_llm),
) -> dict:
    _session_or_404(storage, body.session_id)
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="content is required")
    return await handle_message(storage, llm, body.session_id, body.content)


@router.post("/upload")
async def post_upload(
    session_id: str = Form(),
    kind: str = Form("data"),
    files: list[UploadFile] = File(),
    storage: Storage = Depends(get_storage),
    llm: LLMProvider = Depends(get_llm),
) -> dict:
    _session_or_404(storage, session_id)
    if not files:
        raise HTTPException(status_code=400, detail="files are required")
    blobs: list[tuple[str, bytes]] = []
    for item in files:
        name = item.filename or "upload.bin"
        blobs.append((name, await item.read()))
    try:
        return await handle_upload(storage, llm, session_id, kind=kind, files=blobs)
    except (ParseError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/confirm")
def post_confirm(body: ConfirmBody, storage: Storage = Depends(get_storage)) -> dict:
    _session_or_404(storage, body.session_id)
    try:
        return confirm_session(storage, body.session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/handoff")
def post_handoff(body: HandoffBody, storage: Storage = Depends(get_storage)) -> dict:
    _session_or_404(storage, body.session_id)
    return handoff_session(storage, body.session_id)


@router.post("/sync-node")
async def post_sync_node(
    body: SyncNodeBody,
    storage: Storage = Depends(get_storage),
    llm: LLMProvider = Depends(get_llm),
) -> dict:
    _session_or_404(storage, body.session_id)
    try:
        return await sync_node_async(storage, llm, body.session_id, body.node_id, body.config)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"node not found: {body.node_id}") from exc
