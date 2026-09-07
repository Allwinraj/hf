from __future__ import annotations

import hashlib
import re
from typing import Any

from app.core.llm import LLMError, LLMProvider
from app.core.storage import Storage
from app.models.knowledge import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeFact,
    SessionKnowledge,
)

FACTS_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["facts"],
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "kind", "value", "chunk_id"],
                "properties": {
                    "id": {"type": "string"},
                    "kind": {"type": "string"},
                    "value": {},
                    "chunk_id": {"type": "string"},
                },
            },
        }
    },
}

SCHEMA_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["columns"],
    "properties": {
        "columns": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "type"],
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string"},
                    "meaning": {"type": "string"},
                },
            },
        }
    },
}

_HEADING = re.compile(
    r"^(#{1,6}\s+.+|[A-Z][A-Z0-9][A-Z0-9 /&-]{6,}|Section\s+\d+[.:].*|\d+[.)]\s+.+)$"
)
MAX_CHUNK = 1800


def chunk_text(text: str, *, file_id: str) -> list[KnowledgeChunk]:
    lines = text.replace("\r\n", "\n").split("\n")
    sections: list[tuple[str, list[str]]] = []
    heading = "Document"
    buf: list[str] = []
    for line in lines:
        stripped = line.strip()
        if _HEADING.match(stripped):
            if any(part.strip() for part in buf):
                sections.append((heading, buf))
            heading = stripped.lstrip("#").strip()
            buf = []
        else:
            buf.append(line)
    if buf or not sections:
        sections.append((heading, buf))

    chunks: list[KnowledgeChunk] = []
    order = 0
    for heading, body_lines in sections:
        body = "\n".join(body_lines).strip()
        if not body and heading == "Document":
            continue
        pieces = _split_size(body or heading)
        for piece in pieces:
            digest = hashlib.sha1(f"{file_id}:{order}:{piece[:80]}".encode()).hexdigest()[:10]
            chunks.append(
                KnowledgeChunk(
                    id=f"{file_id}-{digest}",
                    heading=heading,
                    text=piece,
                    order=order,
                )
            )
            order += 1
    if not chunks:
        digest = hashlib.sha1(f"{file_id}:empty".encode()).hexdigest()[:10]
        chunks.append(
            KnowledgeChunk(id=f"{file_id}-{digest}", heading="Document", text=text, order=0)
        )
    return chunks


def _split_size(text: str) -> list[str]:
    if len(text) <= MAX_CHUNK:
        return [text] if text else []
    parts: list[str] = []
    remaining = text
    while remaining:
        parts.append(remaining[:MAX_CHUNK])
        remaining = remaining[MAX_CHUNK:]
    return parts


async def extract_facts(
    llm: LLMProvider,
    chunks: list[KnowledgeChunk],
) -> list[KnowledgeFact]:
    catalog = "\n\n".join(
        f"[chunk_id={c.id} heading={c.heading}]\n{c.text}" for c in chunks
    )
    prompt = (
        "Extract structured finance policy facts from these document chunks. "
        "kind must be one of: threshold, constraint, entity, formula, expected_outcome. "
        "Each fact must cite a chunk_id from the list. Do not invent chunk ids.\n\n"
        f"{catalog}"
    )
    try:
        payload = await llm.complete_json("extraction", prompt, FACTS_JSON_SCHEMA)
    except LLMError:
        return []
    facts: list[KnowledgeFact] = []
    known = {c.id for c in chunks}
    for raw in payload.get("facts") or []:
        chunk_id = raw.get("chunk_id")
        if chunk_id not in known:
            continue
        facts.append(
            KnowledgeFact(
                id=str(raw["id"]),
                kind=str(raw["kind"]),
                value=raw.get("value"),
                chunk_id=chunk_id,
            )
        )
    return facts


def save_knowledge(storage: Storage, knowledge: SessionKnowledge) -> None:
    storage.write_json(
        knowledge.model_dump(mode="json"),
        "knowledge",
        f"{knowledge.session_id}.json",
    )


def load_knowledge(storage: Storage, session_id: str) -> SessionKnowledge:
    return SessionKnowledge.model_validate(
        storage.read_json("knowledge", f"{session_id}.json")
    )


def upsert_document(
    knowledge: SessionKnowledge,
    document: KnowledgeDocument,
) -> SessionKnowledge:
    others = [d for d in knowledge.documents if d.file_id != document.file_id]
    knowledge.documents = others + [document]
    return knowledge


_TOKEN = re.compile(r"[a-z0-9]{3,}")


def rank_chunks(
    knowledge: SessionKnowledge,
    query: str,
    *,
    limit: int = 3,
) -> list[tuple[str, float]]:
    """Score chunks by token overlap. Callers must `retrieve(chunk_id)` for text."""
    tokens = set(_TOKEN.findall((query or "").lower()))
    if not tokens:
        return []
    scored: list[tuple[str, float]] = []
    for document in knowledge.documents:
        for chunk in document.chunks:
            hay = f"{chunk.heading}\n{chunk.text}".lower()
            found = set(_TOKEN.findall(hay))
            if not found:
                continue
            score = len(tokens & found) / len(tokens)
            if score > 0:
                scored.append((chunk.id, score))
        for fact in document.facts:
            blob = f"{fact.kind} {fact.value}".lower()
            found = set(_TOKEN.findall(blob))
            hit = len(tokens & found) / len(tokens) if tokens else 0
            if hit > 0 and fact.chunk_id:
                scored.append((fact.chunk_id, hit * 0.5))
    best: dict[str, float] = {}
    for chunk_id, score in scored:
        if score > best.get(chunk_id, -1):
            best[chunk_id] = score
    ranked = sorted(best.items(), key=lambda item: item[1], reverse=True)
    return ranked[:limit]
