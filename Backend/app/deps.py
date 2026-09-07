from __future__ import annotations

from fastapi import Request

from app.agents.base import AgentRegistry
from app.core.llm import LLMProvider
from app.core.storage import Storage


def get_storage(request: Request) -> Storage:
    return request.app.state.storage


def get_llm(request: Request) -> LLMProvider:
    return request.app.state.llm


def get_registry(request: Request) -> AgentRegistry:
    return request.app.state.registry
