from __future__ import annotations

from app.core.storage import Storage
from app.models.chat import InterviewSession
from app.models.pipeline import Pipeline


def save_session(storage: Storage, session: InterviewSession) -> None:
    storage.write_json(session.model_dump(mode="json"), "sessions", f"{session.id}.json")


def load_session(storage: Storage, session_id: str) -> InterviewSession:
    return InterviewSession.model_validate(storage.read_json("sessions", f"{session_id}.json"))


def session_pipeline(session: InterviewSession) -> Pipeline:
    if session.pipeline:
        return Pipeline.model_validate(session.pipeline)
    return Pipeline(id=session.id, name="draft", version="0.1")


def store_pipeline(session: InterviewSession, pipeline: Pipeline) -> None:
    session.pipeline = pipeline.model_dump(mode="json")
