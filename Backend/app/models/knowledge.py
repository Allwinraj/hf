from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class KnowledgeChunk(BaseModel):
    id: str
    heading: str = ""
    text: str
    order: int = 0


class KnowledgeFact(BaseModel):
    id: str
    kind: str
    value: Any
    chunk_id: str | None = None


class KnowledgeDocument(BaseModel):
    file_id: str
    original_path: str
    chunks: list[KnowledgeChunk] = Field(default_factory=list)
    facts: list[KnowledgeFact] = Field(default_factory=list)


class SessionKnowledge(BaseModel):
    """In-memory/file schema. LLM extract + disk I/O is Phase 3A."""

    session_id: str
    documents: list[KnowledgeDocument] = Field(default_factory=list)

    def retrieve(self, chunk_id: str) -> KnowledgeChunk:
        for document in self.documents:
            for chunk in document.chunks:
                if chunk.id == chunk_id:
                    return chunk
        raise KeyError(chunk_id)

    def facts(self) -> list[KnowledgeFact]:
        return [fact for document in self.documents for fact in document.facts]
