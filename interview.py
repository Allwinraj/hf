from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from app.core.llm import LLMError, LLMProvider
from app.core.logging import new_id
from app.core.storage import Storage
from app.engine.reveal import apply_reveal
from app.engine.schema_sync import propagate_schema
from app.models.chat import ChatMessage, ConfigPatch, ExtractedRequirement, InterviewSession, ProgressiveReveal
from app.models.knowledge import KnowledgeDocument, SessionKnowledge
from app.models.pipeline import Pipeline
from app.services.formulas import (
    catalog_digest,
    compile_math_value,
    compile_math_value_sync,
    looks_like_formula_answer,
    math_phrase_from_session,
)
from app.services.knowledge import (
    chunk_text,
    extract_facts,
    load_knowledge,
    save_knowledge,
    upsert_document,
)
from app.services.parser import ParseError, columns_as_dicts, parse_file
from app.services.pipeline_builder import (
    DECISION_KINDS,
    MATCH_KINDS,
    MATH_KINDS,
    OUTPUT_KINDS,
    capabilities_from,
    reveal_for_session,
    reveal_is_empty,
)
from app.services.sessions import load_session, save_session, session_pipeline, store_pipeline

log = logging.getLogger("nexus.interview")

MIN_QUESTIONS = 5
MAX_QUESTIONS = 15
MAILBOX_MIN_QUESTIONS = 1
MAILBOX_MAX_QUESTIONS = 4
CONFIDENCE_STOP = 0.75

WELCOME_FALLBACK = "Hi — I'm Nexus. What best describes your role?"

SKIP_PHRASES = (
    "no",
    "nope",
    "none",
    "skip",
    "not yet",
    "don't have",
    "do not have",
    "no files",
    "nothing",
    "later",
)

GROUNDING = (
    "When you line these files up, which fields tell you it's the same item?",
    "If the numbers are a little off, how much difference is still acceptable?",
    "What should happen to rows that don't match or sit outside that range?",
    "Who should review exceptions, and is there anything you can auto-approve?",
    "What should I hand you at the end — Excel, PDF, or both?",
    "Can dates drift a day or two, or must they match exactly?",
    "If one row on one side covers several on the other, how should we group them?",
    "Anything else I should lock in before we test this?",
)

TURN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["assistant_message", "requirements", "capabilities"],
    "properties": {
        "assistant_message": {"type": "string"},
        "requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "kind", "value"],
                "properties": {
                    "id": {"type": "string"},
                    "kind": {"type": "string"},
                    "value": {"type": "object"},
                },
            },
        },
        "capabilities": {
            "type": "object",
            "properties": {
                "matcher": {"type": "boolean"},
                "math": {"type": "boolean"},
                "decision": {"type": "boolean"},
                "output": {"type": "boolean"},
                "matcher_stages": {"type": "integer"},
                "math_stages": {"type": "integer"},
                "keys": {"type": "array", "items": {"type": "string"}},
                "output_formats": {"type": "array", "items": {"type": "string"}},
            },
        },
        "ask_question": {"type": "boolean"},
        "question": {"type": ["string", "null"]},
        "ready": {"type": "boolean"},
        "confidence": {"type": "number"},
        "summary": {"type": ["string", "null"]},
        "cannot_serve": {"type": "boolean"},
        "cannot_serve_reason": {"type": ["string", "null"]},
        "answer_relevant": {"type": "boolean"},
        "skip_slot": {"type": "boolean"},
        "is_description": {"type": "boolean"},
    },
}

ONBOARDING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["assistant_message"],
    "properties": {
        "assistant_message": {"type": "string"},
        "next_step": {"type": ["string", "null"]},
        "upload_offer": {"type": ["string", "null"]},
        "capture": {
            "type": ["object", "null"],
            "properties": {
                "role": {"type": ["string", "null"]},
                "industry": {"type": ["string", "null"]},
                "ai_priorities": {"type": ["string", "null"]},
                "description": {"type": ["string", "null"]},
            },
        },
        "virtual_sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": ["string", "null"]},
                    "description": {"type": ["string", "null"]},
                    "columns": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": ["string", "null"]},
                                "type": {"type": ["string", "null"]},
                            },
                        },
                    },
                },
            },
        },
        "requirements": TURN_SCHEMA["properties"]["requirements"],
        "capabilities": TURN_SCHEMA["properties"]["capabilities"],
    },
}

ASK: dict[str, str] = {
    "role": WELCOME_FALLBACK,
    "industry": "Thanks. What industry or sector are you in?",
    "ai_priorities": "If AI could take a few headaches off your plate, which ones matter most?",
    "workflow": "What finance workflow should we build today?",
    "data_prompt": "Do you have working files for this? Attach them below if you do.",
    "data_interview": "No problem — describe one data source: name, file type, and the key columns.",
    "knowledge_prompt": "Any policy, SOP, or reference document to attach? You can skip if not.",
}


def _is_mailbox(session: InterviewSession) -> bool:
    if session.extra.get("mailbox_journey"):
        return True
    return any(
        str(u.get("name") or "").lower().endswith(".eml")
        for u in session.uploads
        if u.get("kind") == "data"
    )


def _min_questions(session: InterviewSession) -> int:
    return MAILBOX_MIN_QUESTIONS if _is_mailbox(session) else MIN_QUESTIONS


def _max_questions(session: InterviewSession) -> int:
    return MAILBOX_MAX_QUESTIONS if _is_mailbox(session) else MAX_QUESTIONS


def _ilog(session: InterviewSession | None, event: str, **fields: Any) -> None:
    sid = session.id[:8] if session else "—"
    step = session.extra.get("onboarding_step") if session else None
    bits = " ".join(f"{k}={v!r}" for k, v in fields.items() if v is not None and v != "")
    log.info("session=%s step=%s | %s %s", sid, step, event, bits)


async def bootstrap_session(storage: Storage, llm: LLMProvider) -> InterviewSession:
    session = InterviewSession(id=new_id(), status="welcome")
    session.extra["onboarding_step"] = "role"
    _ilog(session, "session.create")
    try:
        turn = await _llm_onboarding_turn(llm, session, user_text="", trigger="session_start")
        message = str(turn.get("assistant_message") or ASK["role"])
    except LLMError:
        message = ASK["role"]
        _ilog(session, "session.welcome.fallback")
    assistant = ChatMessage(
        id=new_id(),
        role="assistant",
        content=message,
        meta={"kind": "welcome", "upload_offer": None},
    )
    session.messages.append(assistant)
    save_session(storage, session)
    _ilog(session, "session.ready", reply=assistant.content[:160])
    return session


def create_session(storage: Storage) -> InterviewSession:
    """Sync fallback when no LLM is available (tests)."""
    session = InterviewSession(id=new_id(), status="welcome")
    session.extra["onboarding_step"] = "role"
    session.messages.append(
        ChatMessage(
            id=new_id(),
            role="assistant",
            content=WELCOME_FALLBACK,
            meta={"kind": "welcome"},
        )
    )
    save_session(storage, session)
    return session


async def handle_message(
    storage: Storage,
    llm: LLMProvider,
    session_id: str,
    content: str,
) -> dict[str, Any]:
    session = load_session(storage, session_id)
    user = ChatMessage(id=new_id(), role="user", content=content)
    session.messages.append(user)
    step = str(session.extra.get("onboarding_step") or "done")
    _ilog(session, "user.message", text=content[:200], phase=step)
    if step != "done":
        return await _handle_onboarding(storage, llm, session, content, step, user.id)
    turn = await _llm_turn(llm, session, content, trigger="message")
    turn = _stabilize_interview_turn(session, content, turn)
    return await _apply_turn(storage, llm, session, turn, user.id)


async def handle_upload(
    storage: Storage,
    llm: LLMProvider,
    session_id: str,
    *,
    kind: str,
    files: list[tuple[str, bytes]],
) -> dict[str, Any]:
    session = load_session(storage, session_id)
    if kind not in {"data", "knowledge"}:
        raise ValueError("kind must be data or knowledge")
    saved: list[dict[str, Any]] = []
    for filename, blob in files:
        record = await _store_upload(storage, llm, session, kind, filename, blob)
        session.uploads.append(record)
        saved.append(record)
    names = [s["name"] for s in saved]
    label = "reference document" if kind == "knowledge" else "working file"
    if len(names) != 1:
        label = "reference documents" if kind == "knowledge" else "working files"
    note = f"Attached {label}: " + ", ".join(names)
    user = ChatMessage(
        id=new_id(),
        role="user",
        content=note,
        meta={
            "kind": "upload",
            "upload_kind": kind,
            "files": [{"name": s["name"], "file_id": s["file_id"]} for s in saved],
        },
    )
    session.messages.append(user)
    if session.status == "welcome":
        session.status = "collecting"
    step = str(session.extra.get("onboarding_step") or "done")
    _ilog(session, "user.upload", kind=kind, files=[s["name"] for s in saved], phase=step)

    if kind == "data" and step == "data_prompt":
        session.extra["onboarding_step"] = "knowledge_prompt"
        session.extra["upload_offer"] = "knowledge"
        reveal = _maybe_reveal(session)
        try:
            turn = await _llm_onboarding_turn(llm, session, note, trigger="data_uploaded")
        except LLMError:
            turn = {"assistant_message": ASK["knowledge_prompt"]}
        _apply_onboarding_fields(session, turn, allow_step=False)
        session.extra["onboarding_step"] = "knowledge_prompt"
        session.extra["upload_offer"] = "knowledge"
        assistant = ChatMessage(
            id=new_id(),
            role="assistant",
            content=str(turn.get("assistant_message") or "Any policy or reference documents to attach?"),
            meta={"kind": "onboarding", "upload_offer": "knowledge"},
        )
        session.messages.append(assistant)
        save_session(storage, session)
        _ilog(session, "upload.data.done", reveal=bool(reveal), reply=assistant.content[:160])
        result = _response(session, assistant, reveal, user_message=user)
        result["uploads"] = saved
        return result

    if kind == "knowledge" and step == "knowledge_prompt":
        session.extra["onboarding_step"] = "done"
        session.extra.pop("upload_offer", None)
        _ilog(session, "upload.knowledge.start")
        turn = await _llm_turn(llm, session, note, trigger="upload")
        turn = _stabilize_interview_turn(session, note, turn)
        result = await _apply_turn(storage, llm, session, turn, user.id)
        result["user_message"] = user.model_dump(mode="json")
        result["uploads"] = saved
        return result

    turn = await _llm_turn(llm, session, note, trigger="upload")
    turn = _stabilize_interview_turn(session, note, turn)
    result = await _apply_turn(storage, llm, session, turn, user.id)
    result["user_message"] = user.model_dump(mode="json")
    result["uploads"] = saved
    return result


def confirm_session(storage: Storage, session_id: str) -> dict[str, Any]:
    session = load_session(storage, session_id)
    pipeline = session_pipeline(session)
    if not pipeline.nodes:
        raise ValueError("cannot confirm an empty draft")
    if session.status == "handoff":
        raise ValueError("handoff sessions cannot be confirmed")
    session.confirmed = True
    session.status = "confirmed"
    brief = str(session.extra.get("pipeline_brief") or _pipeline_brief(session))
    session.extra["pipeline_brief"] = brief
    session.summary = brief
    assistant = ChatMessage(
        id=new_id(),
        role="assistant",
        content=(
            "Confirmed.\n\n"
            f"{brief}\n\n"
            "Next: Save this to the Super Agents library. You run it from the library "
            "with files that use the same names (values can change)."
        ),
        meta={"kind": "confirm"},
    )
    session.messages.append(assistant)
    save_session(storage, session)
    return _response(session, assistant, None)


def handoff_session(storage: Storage, session_id: str) -> dict[str, Any]:
    session = load_session(storage, session_id)
    pipeline = session_pipeline(session)
    session.status = "handoff"
    session.confirmed = False
    session.summary = session.summary or _fallback_summary(session, pipeline)
    session.extra["handoff"] = {
        "question_count": session.question_count,
        "node_ids": [n.id for n in pipeline.nodes],
        "requirements": [r.model_dump(mode="json") for r in session.requirements],
    }
    assistant = ChatMessage(
        id=new_id(),
        role="assistant",
        content=(
            "I've connected this draft to a Nexus expert in the product UI. "
            "The canvas and a structured summary are saved — nothing was published "
            "to the Super Agent library.\n\n"
            f"{session.summary}"
        ),
        meta={"kind": "handoff"},
    )
    session.messages.append(assistant)
    save_session(storage, session)
    return _response(session, assistant, None)


def sync_node(
    storage: Storage,
    session_id: str,
    node_id: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    session = load_session(storage, session_id)
    current = session_pipeline(session)
    if node_id not in current.node_map():
        raise KeyError(node_id)
    overrides = dict(session.extra.get("node_overrides") or {})
    overrides[node_id] = {**dict(overrides.get(node_id) or {}), **config}
    session.extra["node_overrides"] = overrides
    delta = ProgressiveReveal(config_patches=[ConfigPatch(node_id=node_id, config=config)])
    updated = apply_reveal(current, delta)
    node = updated.get_node(node_id)
    if node.agent == "ingestion":
        updated = propagate_schema(updated, node_id)
    store_pipeline(session, updated)
    req = ExtractedRequirement(
        id=f"sync-{node_id}",
        kind="config",
        value={"node_id": node_id, "config": config},
    )
    session.requirements = [r for r in session.requirements if r.id != req.id] + [req]
    assistant = ChatMessage(
        id=new_id(),
        role="assistant",
        content=f"Updated {node.label or node_id} from the canvas. Config is now the source of truth.",
        meta={"kind": "sync-node", "node_id": node_id},
    )
    session.messages.append(assistant)
    save_session(storage, session)
    return _response(session, assistant, delta)


async def sync_node_async(
    storage: Storage,
    llm: LLMProvider,
    session_id: str,
    node_id: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    node_cfg = dict(config)
    if node_cfg.get("formula_en") or node_cfg.get("catalog_id"):
        try:
            node_cfg = await compile_math_value(node_cfg, llm)
        except Exception:
            _ilog(None, "math.compile.sync.failed")
    return sync_node(storage, session_id, node_id, node_cfg)


async def _handle_onboarding(
    storage: Storage,
    llm: LLMProvider,
    session: InterviewSession,
    content: str,
    step: str,
    user_id: str,
) -> dict[str, Any]:
    try:
        turn = await _llm_onboarding_turn(llm, session, content, trigger="onboarding")
    except LLMError:
        turn = {}
        _ilog(session, "onboarding.fallback", step=step)
    progress = _advance_onboarding(step, content)
    _apply_onboarding_fields(session, progress)
    _apply_onboarding_fields(session, turn, allow_step=False)
    next_step = str(progress.get("next_step") or step)
    session.extra["onboarding_step"] = next_step
    if next_step == "data_prompt":
        session.extra["upload_offer"] = "data"
    elif next_step == "knowledge_prompt":
        session.extra["upload_offer"] = "knowledge"
    else:
        session.extra.pop("upload_offer", None)
    if not str(turn.get("assistant_message") or "").strip():
        turn["assistant_message"] = ASK.get(next_step, "Got it.")
    if next_step == "knowledge_prompt" and not session.extra.get("virtual_sources"):
        session.extra["virtual_sources"] = _virtual_sources_from_text(content)
    _ilog(
        session,
        "onboarding.llm",
        next=next_step,
        offer=session.extra.get("upload_offer"),
        virtual=len(session.extra.get("virtual_sources") or []),
    )

    if next_step == "done":
        session.extra["onboarding_step"] = "done"
        session.extra.pop("upload_offer", None)
        session.status = "collecting"
        seed = str(session.extra.get("description") or content)
        interview = await _llm_turn(llm, session, seed, trigger="onboarding_done")
        interview = _stabilize_interview_turn(session, seed, interview)
        if not interview.get("requirements") and turn.get("requirements"):
            interview["requirements"] = turn["requirements"]
        if not interview.get("capabilities") and turn.get("capabilities"):
            interview["capabilities"] = turn["capabilities"]
        interview["is_description"] = True
        interview["cannot_serve"] = bool(interview.get("cannot_serve") or turn.get("cannot_serve"))
        if turn.get("cannot_serve_reason") and not interview.get("cannot_serve_reason"):
            interview["cannot_serve_reason"] = turn["cannot_serve_reason"]
        return await _apply_turn(storage, llm, session, interview, user_id)

    reveal = _maybe_reveal(session)
    assistant = ChatMessage(
        id=new_id(),
        role="assistant",
        content=str(turn.get("assistant_message") or "Got it."),
        meta={
            "kind": "onboarding",
            "upload_offer": session.extra.get("upload_offer"),
        },
    )
    session.messages.append(assistant)
    save_session(storage, session)
    _ilog(session, "onboarding.reply", reveal=bool(reveal), reply=assistant.content[:160])
    return _response(session, assistant, reveal)


def _apply_onboarding_fields(
    session: InterviewSession,
    turn: dict[str, Any],
    *,
    allow_step: bool = True,
) -> None:
    for key, val in (turn.get("capture") or {}).items():
        if val:
            session.extra[key] = val
    if turn.get("capture", {}).get("description"):
        session.extra["description"] = turn["capture"]["description"]
    incoming = turn.get("virtual_sources") or []
    if incoming:
        existing = list(session.extra.get("virtual_sources") or [])
        seen = {(s.get("label"), s.get("description")) for s in existing}
        for src in incoming:
            key = (src.get("label"), src.get("description"))
            if key not in seen:
                existing.append(src)
                seen.add(key)
        session.extra["virtual_sources"] = existing
        _ilog(session, "virtual.sources", count=len(existing), labels=[s.get("label") for s in existing])
    next_step = turn.get("next_step")
    if allow_step and next_step:
        session.extra["onboarding_step"] = next_step
    offer = turn.get("upload_offer")
    if offer in {"data", "knowledge"}:
        session.extra["upload_offer"] = offer
    elif allow_step and next_step not in {"data_prompt", "knowledge_prompt"}:
        session.extra.pop("upload_offer", None)
    if turn.get("capabilities"):
        session.extra["capabilities"] = {
            **dict(session.extra.get("capabilities") or {}),
            **turn["capabilities"],
        }
        if _is_mailbox(session):
            session.extra["capabilities"].update(
                {
                    "matcher": False,
                    "math": False,
                    "decision": True,
                    "output": True,
                    "matcher_stages": 0,
                    "math_stages": 0,
                }
            )
    if turn.get("requirements"):
        _merge_requirements(session, turn["requirements"], "onboarding")


def _advance_onboarding(step: str, user_text: str) -> dict[str, Any]:
    text = user_text.strip()
    if step in {"start", "role"}:
        return {"next_step": "industry", "capture": {"role": text}, "upload_offer": None}
    if step == "industry":
        return {"next_step": "ai_priorities", "capture": {"industry": text}, "upload_offer": None}
    if step == "ai_priorities":
        return {"next_step": "workflow", "capture": {"ai_priorities": text}, "upload_offer": None}
    if step == "workflow":
        return {
            "next_step": "data_prompt",
            "capture": {"description": text},
            "upload_offer": "data",
        }
    if step == "data_prompt":
        if _is_skip(text):
            return {"next_step": "data_interview", "upload_offer": None}
        return {"next_step": "data_prompt", "upload_offer": "data"}
    if step == "data_interview":
        return {"next_step": "knowledge_prompt", "upload_offer": "knowledge"}
    if step == "knowledge_prompt":
        if _is_skip(text):
            return {"next_step": "done", "upload_offer": None}
        return {"next_step": "knowledge_prompt", "upload_offer": "knowledge"}
    return {"next_step": step or "role"}


def _is_skip(text: str) -> bool:
    lower = text.strip().lower()
    return any(p in lower for p in SKIP_PHRASES)


def _has_data_upload(session: InterviewSession) -> bool:
    return any(u.get("kind") == "data" for u in session.uploads)


def _maybe_reveal(session: InterviewSession) -> ProgressiveReveal | None:
    if not _can_draft(session):
        return None
    delta = reveal_for_session(session)
    if reveal_is_empty(delta):
        return None
    updated = apply_reveal(session_pipeline(session), delta)
    store_pipeline(session, updated)
    if session.status in {"welcome", "collecting"}:
        session.status = "interview"
    return delta


def _virtual_sources_from_text(text: str) -> list[dict[str, Any]]:
    """Parse 'bank csv with date, amount; ledger with date, amount' without an LLM."""
    sources: list[dict[str, Any]] = []
    for chunk in re.split(r"[;\n]+", str(text or "")):
        part = chunk.strip()
        if not part:
            continue
        cols = re.findall(
            r"\b(date|amount|id|name|number|total|qty|quantity|line|po|invoice|customer|vendor)\b",
            part.lower(),
        )
        label_match = re.match(r"^([A-Za-z][A-Za-z0-9 _-]{0,40})", part)
        label = (label_match.group(1).strip() if label_match else part.split()[0]).lower()
        sources.append(
            {
                "label": label.replace(" ", "_"),
                "description": part,
                "columns": [{"name": c, "type": "string"} for c in dict.fromkeys(cols)],
            }
        )
    return sources


def _req_by_kind(requirements: list[dict[str, Any]], kinds: set[str]) -> dict[str, Any] | None:
    for raw in requirements:
        if str(raw.get("kind") or "").lower() in kinds:
            return raw
    return None


def _ensure_requirement(
    requirements: list[dict[str, Any]],
    req_id: str,
    kind: str,
) -> dict[str, Any]:
    existing = next((raw for raw in requirements if raw.get("id") == req_id), None)
    if existing:
        return existing
    created = {"id": req_id, "kind": kind, "value": {}}
    requirements.append(created)
    return created


def _filter_requirements_by_capabilities(
    requirements: list[Any],
    caps: dict[str, Any],
) -> list[Any]:
    """Drop stale requirements when an agent was removed from the canvas."""
    kept: list[Any] = []
    for req in requirements:
        kind = str(getattr(req, "kind", req.get("kind") if isinstance(req, dict) else "")).lower()
        if kind in MATCH_KINDS and not caps.get("matcher"):
            continue
        if kind in MATH_KINDS and not caps.get("math"):
            continue
        if kind in DECISION_KINDS and not caps.get("decision"):
            continue
        if kind in OUTPUT_KINDS and not caps.get("output"):
            continue
        kept.append(req)
    return kept


def _backfill_math_only(
    session: InterviewSession,
    turn: dict[str, Any],
    user_text: str,
) -> None:
    """Only fill math when the user actually answered a tolerance question.

    Broader backfill was forcing extra interview slots and breaking the flow.
    """
    text = str(user_text or "").strip()
    if not text:
        return
    pending = str(session.extra.get("pending_slot") or "")
    if pending != "tolerance_or_formula" and not looks_like_formula_answer(text):
        return
    requirements = list(turn.get("requirements") or [])
    math = _req_by_kind(requirements, MATH_KINDS) or _ensure_requirement(requirements, "math-1", "math")
    value = math.setdefault("value", {})
    if not value.get("formula_en") and not value.get("catalog_id"):
        value["formula_en"] = text
    hydrated = compile_math_value_sync(value)
    if hydrated.get("ast"):
        math["value"] = hydrated
    turn["requirements"] = requirements


def _stabilize_interview_turn(
    session: InterviewSession,
    user_text: str,
    turn: dict[str, Any],
) -> dict[str, Any]:
    """Light touch-up only — trust the model for capabilities and questions."""
    normalized = dict(turn or {})
    if normalized.get("answer_relevant") is None:
        normalized["answer_relevant"] = True
    if normalized.get("confidence") is None:
        normalized["confidence"] = 0.5
    if normalized.get("ready") is None:
        normalized["ready"] = False
    _backfill_math_only(session, normalized, user_text)
    return normalized


async def _apply_turn(
    storage: Storage,
    llm: LLMProvider,
    session: InterviewSession,
    turn: dict[str, Any],
    source_message_id: str,
) -> dict[str, Any]:
    _ilog(
        session,
        "interview.llm.apply",
        ready=turn.get("ready"),
        confidence=turn.get("confidence"),
        reqs=len(turn.get("requirements") or []),
    )
    relevant = turn.get("answer_relevant")
    if relevant is None:
        relevant = True
    if relevant:
        pending_slot = str(session.extra.get("pending_slot") or "")
        last_user = next((m.content for m in reversed(session.messages) if m.role == "user"), "")
        if pending_slot == "send_details" and last_user:
            session.extra["send_details"] = last_user
        if turn.get("capabilities") is not None:
            session.extra["capabilities"] = {
                **dict(session.extra.get("capabilities") or {}),
                **turn["capabilities"],
            }
            if _is_mailbox(session):
                session.extra["capabilities"].update(
                    {
                        "matcher": False,
                        "math": False,
                        "decision": True,
                        "output": True,
                        "matcher_stages": 0,
                        "math_stages": 0,
                    }
                )
            session.requirements = _filter_requirements_by_capabilities(
                session.requirements,
                dict(session.extra.get("capabilities") or {}),
            )
        _merge_requirements(session, turn.get("requirements") or [], source_message_id)
        await _hydrate_math_from_conversation(llm, session)
    if relevant and turn.get("is_description") and turn.get("assistant_message"):
        session.extra["description"] = session.extra.get("description") or session.messages[-1].content
    if turn.get("cannot_serve") and not _is_mailbox(session):
        session.extra["cannot_serve"] = True
        reason = str(turn.get("cannot_serve_reason") or turn.get("summary") or "").strip()
        session.summary = reason or session.summary or _cannot_serve_summary(session)
        session.extra["suggest_handoff"] = True

    reveal = None
    if _can_draft(session):
        delta = reveal_for_session(session)
        if not reveal_is_empty(delta):
            updated = apply_reveal(session_pipeline(session), delta)
            store_pipeline(session, updated)
            reveal = delta
            if session.status in {"welcome", "collecting"}:
                session.status = "interview"

    if session.extra.get("cannot_serve"):
        if _is_mailbox(session):
            session.extra.pop("cannot_serve", None)
        else:
            return _finish_cannot_serve(storage, session, turn, reveal)

    ready_flag, question = _question_budget(session, turn)
    ack = str(turn.get("assistant_message") or "").strip()
    pending = str(session.extra.get("pending_question") or "").strip()
    retries = int(session.extra.get("question_retries") or 0)
    parts: list[str] = []

    if pending and not relevant and not turn.get("skip_slot"):
        if retries < 1:
            session.extra["question_retries"] = retries + 1
            retry_q = pending
            if ack and not _already_asks(ack, retry_q):
                parts.append(ack)
            parts.append("That didn't quite answer this one — I need it to wire the canvas. Same question:")
            parts.append(retry_q)
            content = "\n\n".join(p for p in parts if p)
            assistant = ChatMessage(
                id=new_id(),
                role="assistant",
                content=content,
                meta={"kind": "retry", "question_count": session.question_count},
            )
            session.messages.append(assistant)
            save_session(storage, session)
            _ilog(session, "interview.retry", retries=retries + 1)
            return _response(session, assistant, reveal)
        skipped = list(session.extra.get("skipped_slots") or [])
        slot = str(session.extra.get("pending_slot") or "this detail")
        if slot not in skipped:
            skipped.append(slot)
        session.extra["skipped_slots"] = skipped
        session.extra["question_retries"] = 0
        session.extra.pop("pending_question", None)
        session.extra.pop("pending_slot", None)
        if ack:
            parts.append(ack)
        parts.append(
            f"I'll skip {slot.replace('_', ' ')} for now and keep building with what we have."
        )
        ready_flag, question = _question_budget(session, {**turn, "ask_question": True, "ready": False})

    if question:
        session.question_count += 1
        session.status = "interview"
        session.extra["pending_question"] = question
        session.extra["pending_slot"] = (_missing_slots(session) or ["next_detail"])[0]
        session.extra["question_retries"] = 0
        if _already_asks(ack, question):
            if ack not in parts:
                parts.append(ack)
        else:
            if ack and ack not in parts:
                parts.append(ack)
            parts.append(question)
        if session.question_count >= _max_questions(session):
            session.extra["suggest_handoff"] = True
    elif ack:
        if ack not in parts:
            parts.append(ack)
        session.extra.pop("pending_question", None)
        session.extra["question_retries"] = 0
    if turn.get("summary"):
        session.summary = str(turn["summary"])
    if ready_flag:
        session.status = "ready_to_confirm"
        session.extra["ready_to_confirm"] = True
        session.extra.pop("pending_question", None)
        if session.summary:
            parts.append(session.summary)
        skipped = session.extra.get("skipped_slots") or []
        if skipped:
            parts.append(
                "I skipped: " + ", ".join(str(s).replace("_", " ") for s in skipped) + "."
            )
        brief = _pipeline_brief(session)
        session.extra["pipeline_brief"] = brief
        session.summary = brief
        parts.append(brief)
        parts.append("Read this through. If it matches what you need, confirm the pipeline — then Save it to the library to run it.")
    if session.extra.get("suggest_handoff") and session.status != "ready_to_confirm":
        parts.append(
            "If this is more than Nexus can finish here, connect to a Nexus expert below — "
            "I'll pass the draft canvas and a summary of what's missing."
        )

    content = "\n\n".join(p for p in parts if p) or "Got it."
    assistant = ChatMessage(
        id=new_id(),
        role="assistant",
        content=content,
        meta={"kind": "turn", "ready": ready_flag, "question_count": session.question_count},
    )
    session.messages.append(assistant)
    save_session(storage, session)
    _ilog(session, "interview.reply", status=session.status, reveal=bool(reveal), ready=ready_flag)
    return _response(session, assistant, reveal)


def _cannot_serve_summary(session: InterviewSession) -> str:
    desc = session.extra.get("description") or "this process"
    return (
        f"Nexus v1 can ingest files, match records, run math gates, apply a decision policy, "
        f"and export Excel/PDF. It cannot complete {desc!s} as described — for example live ERP "
        "writes, Slack/Teams dispatch, or work outside those five agents."
    )


def _finish_cannot_serve(
    storage: Storage,
    session: InterviewSession,
    turn: dict[str, Any],
    reveal: ProgressiveReveal | None,
) -> dict[str, Any]:
    why = session.summary or _cannot_serve_summary(session)
    session.summary = why
    session.extra["suggest_handoff"] = True
    ack = str(turn.get("assistant_message") or "").strip()
    parts = [
        ack,
        why,
        "Connect to a Nexus expert below and I'll freeze this draft plus a summary of why we stopped.",
    ]
    assistant = ChatMessage(
        id=new_id(),
        role="assistant",
        content="\n\n".join(p for p in parts if p),
        meta={"kind": "cannot_serve", "suggest_handoff": True},
    )
    session.messages.append(assistant)
    save_session(storage, session)
    _ilog(session, "interview.cannot_serve")
    return _response(session, assistant, reveal)


def _question_budget(session: InterviewSession, turn: dict[str, Any]) -> tuple[bool, str | None]:
    if session.status in {"confirmed", "handoff"}:
        return False, None
    confidence = float(turn.get("confidence") or 0)
    llm_ready = bool(turn.get("ready"))
    cannot = bool(turn.get("cannot_serve") or session.extra.get("cannot_serve"))
    if cannot and not _is_mailbox(session):
        return False, None
    drafted = _can_draft(session)
    if not drafted:
        return False, None
    missing = _missing_slots(session)
    want_ask = bool(turn.get("ask_question", True))
    question = (turn.get("question") or "").strip() or None
    min_q = _min_questions(session)
    max_q = _max_questions(session)
    if session.question_count >= max_q:
        if missing and not _is_mailbox(session):
            session.extra["suggest_handoff"] = True
            return False, None
        return True, None
    if not _is_mailbox(session) and session.question_count >= 12 and missing:
        session.extra["suggest_handoff"] = True
    if session.question_count < min_q:
        return False, question or _fallback_question(session)
    if not missing or (llm_ready and confidence >= CONFIDENCE_STOP):
        return True, None
    if llm_ready and not want_ask and not missing:
        return True, None
    if want_ask or missing:
        return False, question or _fallback_question(session)
    if llm_ready:
        return True, None
    return False, None


def _can_draft(session: InterviewSession) -> bool:
    has_description = bool(session.extra.get("description"))
    has_data = _has_data_upload(session)
    has_virtual = bool(session.extra.get("virtual_sources"))
    ok = bool(has_description and (has_data or has_virtual))
    _ilog(session, "draft.check", ok=ok, files=has_data, virtual=has_virtual)
    return ok


def _already_asks(ack: str, question: str) -> bool:
    if not ack:
        return False
    q = question.strip().casefold()
    a = ack.strip().casefold()
    if q and q in a:
        return True
    return ack.strip().endswith("?") and "?" in ack


def _req_lookup(session: InterviewSession, kinds: set[str]) -> dict:
    for req in reversed(session.requirements):
        if req.kind.lower() in kinds:
            return dict(req.value or {})
    return {}


def _missing_slots(session: InterviewSession) -> list[str]:
    caps = capabilities_from(session)
    missing: list[str] = []
    match = _req_lookup(session, MATCH_KINDS)
    math = _req_lookup(session, MATH_KINDS)
    decision = _req_lookup(session, DECISION_KINDS)
    output = _req_lookup(session, OUTPUT_KINDS)
    if _is_mailbox(session):
        if not str(session.extra.get("send_details") or "").strip():
            missing.append("send_details")
        if caps.get("decision") and not decision.get("policy"):
            missing.append("exception_routing")
        return missing
    if caps.get("matcher") and not (match.get("keys") or (session.extra.get("capabilities") or {}).get("keys")):
        missing.append("match_keys")
    if caps.get("math") and not (math.get("formula_en") or math.get("ast") or math.get("catalog_id") or math.get("threshold") is not None):
        missing.append("tolerance_or_formula")
    if caps.get("decision") and not decision.get("policy"):
        missing.append("exception_routing")
    formats = list((session.extra.get("capabilities") or {}).get("output_formats") or output.get("formats") or [])
    if caps.get("output") and not formats:
        missing.append("output_format")
    return missing


def _question_candidates(session: InterviewSession) -> list[str]:
    """Questions worth asking next, open slots first."""
    by_slot = {
        "match_keys": "When you line these files up, which fields tell you it's the same item?",
        "tolerance_or_formula": "If the numbers are a little off, how much difference is still acceptable?",
        "exception_routing": "When something doesn't match, who reviews it — and is there anything you can auto-approve?",
        "output_format": "What should I hand you at the end — Excel, PDF, or both?",
        "send_details": "Who should the draft reply be from, what tone, and confirm a human must click Send on the dashboard before anything goes out?",
    }
    if _is_mailbox(session):
        preview = session.extra.get("mailbox_preview") or {}
        subject = preview.get("subject") or "this PR mail"
        by_slot["exception_routing"] = (
            f"For mails like “{subject}”, which uploaded policy rules must fail the PR versus only warn?"
        )
        by_slot["body_vs_pdf"] = (
            "The body has a short PR summary and the PDF (if any) has the spec. "
            "What should we extract as the PR line, and should the PDF win if they differ?"
        )
        candidates = [by_slot[slot] for slot in _missing_slots(session) if slot in by_slot]
        if "body_vs_pdf" not in _missing_slots(session):
            candidates.append(by_slot["body_vs_pdf"])
        return candidates or [by_slot["send_details"]]
    candidates = [by_slot[slot] for slot in _missing_slots(session) if slot in by_slot]
    caps = capabilities_from(session)
    if caps.get("matcher") and not _req_lookup(session, MATCH_KINDS).get("window_days"):
        candidates.append("Can the dates drift by a day or two, or do they need to match exactly?")
    start = session.question_count % len(GROUNDING)
    candidates.extend(GROUNDING[start:] + GROUNDING[:start])
    return candidates


def _fallback_question(session: InterviewSession) -> str:
    return _question_candidates(session)[0]


def _merge_requirements(
    session: InterviewSession,
    incoming: list[dict[str, Any]],
    source_message_id: str,
) -> None:
    by_id = {r.id: r for r in session.requirements}
    for raw in incoming:
        item = ExtractedRequirement(
            id=str(raw["id"]),
            kind=str(raw["kind"]),
            value=dict(raw.get("value") or {}),
            source_message_id=source_message_id,
        )
        by_id[item.id] = item
        session.requirements = list(by_id.values())


async def _hydrate_math_from_conversation(llm: LLMProvider, session: InterviewSession) -> None:
    updated: list[ExtractedRequirement] = []
    changed = False
    for req in session.requirements:
        if req.kind.lower() not in MATH_KINDS:
            updated.append(req)
            continue
        value = dict(req.value or {})
        hydrated = compile_math_value_sync(value)
        if not hydrated.get("ast"):
            phrase = math_phrase_from_session(session)
            if phrase:
                hydrated = compile_math_value_sync({**value, "formula_en": phrase})
        if not hydrated.get("ast") and (value.get("formula_en") or value.get("catalog_id") or value.get("ast")):
            try:
                hydrated = await compile_math_value(value, llm)
            except Exception:
                _ilog(session, "math.compile.skip", req=req.id)
                hydrated = value
        if hydrated != dict(req.value or {}):
            changed = True
            _ilog(
                session,
                "math.compile.ok",
                req=req.id,
                catalog=hydrated.get("catalog_id"),
                ast=str(hydrated.get("ast") or "")[:80],
            )
        updated.append(req.model_copy(update={"value": hydrated}))
    if changed:
        session.requirements = updated
        overrides = dict(session.extra.get("node_overrides") or {})
        math_ids = [
            n.id for n in session_pipeline(session).nodes if n.agent == "math"
        ] or ["math"]
        math_vals = [r.value for r in updated if r.kind.lower() in MATH_KINDS]
        for i, nid in enumerate(math_ids):
            cfg = math_vals[i] if i < len(math_vals) else (math_vals[-1] if math_vals else {})
            overrides[nid] = {**dict(overrides.get(nid) or {}), **cfg}
        session.extra["node_overrides"] = overrides


def _conversation_snapshot(session: InterviewSession, user_text: str, trigger: str) -> dict[str, Any]:
    pipeline = session_pipeline(session)
    return {
        "trigger": trigger,
        "user_text": user_text,
        "onboarding_step": session.extra.get("onboarding_step"),
        "status": session.status,
        "question_count": session.question_count,
        "role": session.extra.get("role"),
        "industry": session.extra.get("industry"),
        "ai_priorities": session.extra.get("ai_priorities"),
        "description": session.extra.get("description"),
        "virtual_sources": session.extra.get("virtual_sources") or [],
        "uploads": [
            {"file_id": u.get("file_id"), "kind": u.get("kind"), "schema": u.get("schema"), "name": u.get("name")}
            for u in session.uploads
        ],
        "knowledge_facts": session.extra.get("knowledge_facts") or [],
        "recent_messages": [
            {"role": m.role, "content": m.content[:400]}
            for m in session.messages[-8:]
        ],
        "requirements": [r.model_dump(mode="json") for r in session.requirements],
        "capabilities": session.extra.get("capabilities"),
        "missing_slots": _missing_slots(session),
        "mailbox_journey": _is_mailbox(session),
        "mailbox_preview": session.extra.get("mailbox_preview"),
        "send_details": session.extra.get("send_details"),
        "pipeline": {
            "nodes": [
                {
                    "id": n.id,
                    "agent": n.agent,
                    "mode": n.mode,
                    "label": n.label,
                    "config": {
                        k: n.config.get(k)
                        for k in (
                            "keys",
                            "window_days",
                            "flags",
                            "formula_en",
                            "catalog_id",
                            "ast",
                            "gate_ast",
                            "shape",
                            "constants",
                            "policy",
                            "formats",
                            "title",
                        )
                        if k in n.config
                    },
                }
                for n in pipeline.nodes
            ],
            "edges": [
                {"source": e.source, "source_port": e.source_port, "target": e.target}
                for e in pipeline.edges
            ],
        },
        "skipped_slots": session.extra.get("skipped_slots") or [],
        "pending_question": session.extra.get("pending_question"),
        "question_retries": session.extra.get("question_retries") or 0,
        "min_questions": _min_questions(session),
        "max_questions": _max_questions(session),
    }


async def _llm_onboarding_turn(
    llm: LLMProvider,
    session: InterviewSession,
    user_text: str,
    *,
    trigger: str,
) -> dict[str, Any]:
    snapshot = _conversation_snapshot(session, user_text, trigger)
    prompt = (
        "You are Nexus, a finance pipeline co-pilot. Generate the next onboarding message from context.\n"
        "Rules:\n"
        "- Warm, human, concise. assistant_message is 1-2 short sentences max.\n"
        "- Ask exactly ONE crisp question (single line, never a paragraph).\n"
        "- The app owns the step order: role → industry → ai_priorities → workflow → "
        "data_prompt → data_interview (no files) → knowledge_prompt → done. "
        "Do not skip steps. next_step and capture are optional; omit unused capture fields "
        "instead of sending null.\n"
        "- At data_prompt, invite them to attach files. At knowledge_prompt, invite policy/SOP.\n"
        "- If the user has no files, ask how ONE data source looks and fill virtual_sources.\n"
        "- When knowledge is skipped or complete, you may emit initial requirements/capabilities.\n"
        "- Never mention 'data folder', 'knowledge folder', DAG, or agent class names.\n\n"
        f"{json.dumps(snapshot, default=str)}"
    )
    _ilog(session, "llm.onboarding.request", trigger=trigger, user=user_text[:120])
    turn = await llm.complete_json("general", prompt, ONBOARDING_SCHEMA, 0.35)
    _ilog(session, "llm.onboarding.response", next=turn.get("next_step"), offer=turn.get("upload_offer"))
    return turn


async def _llm_turn(
    llm: LLMProvider,
    session: InterviewSession,
    user_text: str,
    *,
    trigger: str,
) -> dict[str, Any]:
    snapshot = _conversation_snapshot(session, user_text, trigger)
    prompt = (
        "You are Nexus, interviewing a finance teammate to design a live ops pipeline.\n"
        "Voice: warm colleague, not a form. assistant_message is a short acknowledgment "
        "(1-2 sentences, no question). Put the ONE interview question in `question`.\n"
        "Never use jargon: Matcher, Math node, Decision agent, DAG, residuals port, "
        "semantic normalization, AST. Speak in business language; still extract the tech.\n"
        "Ask only questions this use case and the current canvas still need. "
        "If Matcher is on the canvas, ask how they pair records (fields, date wiggle room, "
        "one-to-many deposits). If Math is on the canvas, ask for the formula/threshold "
        "in plain words (e.g. '2% or $50, whichever is smaller'). If Decision is on the canvas, "
        "ask who reviews exceptions and any auto-approve rules. If Output is on the canvas, "
        "ask Excel vs PDF. Skip agents that are not in the pipeline.\n"
        "If mailbox_journey is true: this pipeline drafts PR replies from unread mail and a human "
        "clicks Send on the dashboard. That is in scope — never set cannot_serve for email send. "
        "Do not ask Matcher/Math/column-mapping questions. Ask at most 4 questions, grounded in "
        "mailbox_preview (this mail's subject, body excerpt, PDF excerpt). Always cover send_details. "
        "Set capabilities matcher false, math false, decision true, output true.\n"
        "Fill missing_slots first. After each useful answer, update requirements so the "
        "canvas builds in parallel (keys, formula_en, policy, output format).\n"
        "If the user's reply does not answer the pending_question, set answer_relevant false "
        "and do not invent requirements from that reply. We will ask the same question once more. "
        "If they still dodge it, we skip that slot and keep building with what we have.\n"
        "If the process needs live ERP writes, Slack/email dispatch, or anything outside "
        "Ingest / Matcher / Math / Decision / Excel-PDF Output, set cannot_serve true and "
        "cannot_serve_reason to a short plain-language summary of why Nexus v1 cannot finish it.\n"
        "Emit requirements with kinds match|math|decision|output|excel|pdf. "
        "For match: value.keys, mode, window_days, flags.allocation, "
        "flags.group_receipts (several deposits against one obligation), "
        "flags.receipts_only (pair credits/receipts, ignore withdrawals). "
        "For math: copy the user's words into value.formula_en. Pick value.catalog_id "
        "from the formula library below — never invent AST. Fill value.constants "
        "(pct 0.01 for 1%, pct 0.02 for 2%, amount 50 for $50 or 1000 for a $1,000 break) and "
        "value.input_map from uploaded column names. Set value.shape sequential for "
        "running balances, value.mode hybrid when they want a flag/gate.\n"
        "Formula library:\n"
        f"{catalog_digest()}\n"
        "The app copies that catalog formula's AST onto the Math node. "
        "Do not write ast yourself.\n"
        "For decision: value.policy in one sentence. "
        "For output: value.formats ['xlsx'] and/or ['pdf'].\n"
        "Set capabilities from THIS process only. Never insert Matcher, Math, or Decision "
        "as placeholders. Do not add Knowledge ingest unless a knowledge file was uploaded. "
        "Repeat an agent type only for true multi-stage work. "
        "Each answer should refine the live DAG — update keys/formula/policy so the canvas changes.\n"
        "After 5 follow-up questions, set ready true when missing_slots is empty. "
        "Do not invent extra questions. The app stops at 15 and hands over if still unclear. "
        "If mailbox_journey is true, stop by 4 follow-up questions.\n\n"
        f"{json.dumps(snapshot, default=str)}"
    )
    _ilog(session, "llm.interview.request", trigger=trigger, user=user_text[:120])
    turn = await llm.complete_json("general", prompt, TURN_SCHEMA, 0.2)
    _ilog(
        session,
        "llm.interview.response",
        ready=turn.get("ready"),
        confidence=turn.get("confidence"),
    )
    return turn


async def _store_upload(
    storage: Storage,
    llm: LLMProvider,
    session: InterviewSession,
    kind: str,
    filename: str,
    blob: bytes,
) -> dict[str, Any]:
    file_id = _file_id(filename, {u.get("file_id") for u in session.uploads})
    rel = f"uploads/{session.id}/{file_id}{Path(filename).suffix.lower() or '.bin'}"
    path = storage.write_bytes(blob, *rel.split("/"))
    parsed = parse_file(path)
    record: dict[str, Any] = {
        "kind": kind,
        "file_id": file_id,
        "name": filename,
        "path": str(path),
        "label": Path(filename).stem,
    }
    if kind == "data":
        if not parsed.tables:
            raise ParseError("data upload needs a tabular structure")
        table = parsed.tables[0]
        record["schema"] = columns_as_dicts(table.columns)
        record["sheet"] = table.sheet
        record["row_count"] = len(table.rows)
        _ilog(session, "upload.parsed", kind="data", file=filename, rows=len(table.rows), fmt=parsed.fmt)
        if parsed.fmt == "eml" or Path(filename).suffix.lower() == ".eml":
            from app.services.mail import mailbox_preview_from_parsed, parse_rfc822

            session.extra["mailbox_journey"] = True
            session.extra["capabilities"] = {
                **dict(session.extra.get("capabilities") or {}),
                "matcher": False,
                "math": False,
                "decision": True,
                "output": True,
                "output_formats": ["xlsx"],
            }
            parsed_mail = parse_rfc822(path.read_bytes(), uid="sample")
            session.extra["mailbox_preview"] = mailbox_preview_from_parsed(parsed_mail)
    else:
        chunks = chunk_text(parsed.text, file_id=file_id)
        facts = await extract_facts(llm, chunks)
        knowledge = _session_knowledge(storage, session.id)
        upsert_document(
            knowledge,
            KnowledgeDocument(
                file_id=file_id,
                original_path=str(path),
                chunks=chunks,
                facts=facts,
            ),
        )
        save_knowledge(storage, knowledge)
        record["chunk_ids"] = [c.id for c in chunks]
        record["fact_count"] = len(facts)
        session.extra["knowledge_facts"] = [f.model_dump(mode="json") for f in facts[:24]]
    return record


def _session_knowledge(storage: Storage, session_id: str) -> SessionKnowledge:
    if storage.exists("knowledge", f"{session_id}.json"):
        return load_knowledge(storage, session_id)
    return SessionKnowledge(session_id=session_id)


def _file_id(filename: str, taken: set) -> str:
    import re

    base = re.sub(r"[^a-zA-Z0-9_-]+", "_", Path(filename).stem).strip("_") or "file"
    candidate = base[:40]
    n = 2
    while candidate in taken:
        candidate = f"{base[:36]}_{n}"
        n += 1
    return candidate


def _explain_node(node) -> str:
    cfg = dict(node.config or {})
    filename = cfg.get("filename") or Path(str(cfg.get("path") or "")).name
    if node.agent == "ingestion":
        if (node.mode or cfg.get("mode")) == "mailbox":
            return (
                f"Reads unread mail from {cfg.get('username') or 'the mailbox'} "
                f"({cfg.get('folder') or 'INBOX'}) and keeps PR/PO subjects."
            )
        if (node.mode or cfg.get("mode")) == "knowledge":
            return f"Reads the policy/reference file {filename or node.label} and keeps the rules for matching and review."
        if cfg.get("virtual"):
            return f"Uses the described source “{node.label}” until a real file with that shape is attached."
        return f"Reads working file {filename or node.label} and detects its columns."
    if node.agent == "matcher":
        keys = cfg.get("keys") or []
        window = cfg.get("window_days")
        key_bit = ", ".join(str(k) for k in keys) if keys else "the fields you named"
        extra = f" Dates may drift by {window} day(s)." if window not in (None, "") else ""
        return f"Pairs rows that share {key_bit}.{extra} Leftovers and splits go to exceptions."
    if node.agent == "math":
        formula = cfg.get("formula_en") or cfg.get("catalog_id") or "the calculation from the conversation"
        return f"Applies: {formula}."
    if node.agent == "decision":
        policy = cfg.get("policy") or "the review rules from the conversation"
        return f"Flags or approves using: {policy}."
    if node.agent == "output":
        formats = cfg.get("formats") or []
        if cfg.get("mode") == "pdf" or "pdf" in formats:
            kind = "PDF"
        elif cfg.get("mode") == "excel" or "xlsx" in formats:
            kind = "Excel"
        else:
            kind = "Excel/PDF"
        return f"Builds a {kind} report you can download."
    return node.label or node.agent


def _pipeline_brief(session: InterviewSession) -> str:
    pipeline = session_pipeline(session)
    purpose = (
        session.extra.get("description")
        or session.summary
        or "this finance process"
    )
    lines = [
        "Why this pipeline",
        f"• {purpose}",
        "",
        "What each step does",
    ]
    if not pipeline.nodes:
        lines.append("• Nothing on the canvas yet.")
        return "\n".join(lines)
    for i, node in enumerate(pipeline.nodes, 1):
        title = node.label or node.id
        lines.append(f"{i}. {title} — {_explain_node(node)}")
    return "\n".join(lines)


def _fallback_summary(session: InterviewSession, pipeline: Pipeline) -> str:
    agents = [n.agent for n in pipeline.nodes]
    return (
        f"Draft pipeline with {len(pipeline.nodes)} nodes ({', '.join(agents) or 'none'}). "
        f"Requirements captured: {len(session.requirements)}."
    )


def _response(
    session: InterviewSession,
    message: ChatMessage,
    reveal: ProgressiveReveal | None,
    user_message: ChatMessage | None = None,
) -> dict[str, Any]:
    return {
        "session_id": session.id,
        "status": session.status,
        "confirmed": session.confirmed,
        "question_count": session.question_count,
        "ready_to_confirm": session.status == "ready_to_confirm" or session.confirmed,
        "summary": session.summary,
        "upload_offer": session.extra.get("upload_offer"),
        "cannot_serve": bool(session.extra.get("cannot_serve")),
        "suggest_handoff": bool(session.extra.get("suggest_handoff")),
        "user_message": None if user_message is None else user_message.model_dump(mode="json"),
        "message": message.model_dump(mode="json"),
        "reveal": None if reveal is None else reveal.model_dump(mode="json"),
        "pipeline": session.pipeline,
    }
