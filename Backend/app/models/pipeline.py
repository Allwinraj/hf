from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

AgentKind = Literal["ingestion", "matcher", "math", "decision", "output"]
EdgeType = Literal["normal", "conditional"]
ErrorStrategy = Literal["fail_fast", "emit_exceptions"]


class Port(BaseModel):
    name: str
    direction: Literal["in", "out"] = "out"


class Node(BaseModel):
    id: str
    agent: AgentKind
    mode: str = "default"
    behavior_ref: str = ""
    label: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    error_strategy: ErrorStrategy = "emit_exceptions"
    ports: list[Port] = Field(default_factory=list)


class Edge(BaseModel):
    id: str
    source: str
    source_port: str = "default"
    target: str
    target_port: str = "default"
    type: EdgeType = "normal"
    condition: str | None = None


class Pipeline(BaseModel):
    id: str
    name: str = ""
    version: str = "0.1"
    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)

    def node_map(self) -> dict[str, Node]:
        return {node.id: node for node in self.nodes}

    def get_node(self, node_id: str) -> Node:
        for node in self.nodes:
            if node.id == node_id:
                return node
        raise KeyError(node_id)

    def incoming(self, node_id: str) -> list[Edge]:
        return [edge for edge in self.edges if edge.target == node_id]

    def outgoing(self, node_id: str) -> list[Edge]:
        return [edge for edge in self.edges if edge.source == node_id]
