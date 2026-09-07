from __future__ import annotations

from typing import Any

from app.models.pipeline import Node, Pipeline


def apply_schema_overrides(
    node: Node, overrides: dict[str, dict[str, Any]]
) -> tuple[Node, dict[str, str]]:
    """overrides: {original_name: {name?, type?}}"""
    schema = list(node.config.get("schema") or [])
    renamed: dict[str, str] = {}
    updated: list[dict[str, Any]] = []
    for column in schema:
        name = column.get("name")
        patch = overrides.get(name, {})
        new_col = dict(column)
        if "name" in patch and patch["name"] != name:
            renamed[name] = patch["name"]
            new_col["name"] = patch["name"]
        if "type" in patch:
            new_col["type"] = patch["type"]
        updated.append(new_col)
    config = dict(node.config)
    config["schema"] = updated
    config["schema_overrides"] = {**config.get("schema_overrides", {}), **overrides}
    return node.model_copy(update={"config": config}), renamed


def _rewrite_value(value: Any, renamed: dict[str, str]) -> Any:
    if isinstance(value, str):
        return renamed.get(value, value)
    if isinstance(value, list):
        return [_rewrite_value(item, renamed) for item in value]
    if isinstance(value, dict):
        return {key: _rewrite_value(item, renamed) for key, item in value.items()}
    return value


def propagate_schema(pipeline: Pipeline, ingestion_id: str) -> Pipeline:
    """Push ingestion schema (and renames) to every downstream node."""
    graph = pipeline.model_copy(deep=True)
    source = graph.get_node(ingestion_id)
    renamed = {
        old: patch["name"]
        for old, patch in (source.config.get("schema_overrides") or {}).items()
        if "name" in patch and patch["name"] != old
    }
    schema = source.config.get("schema") or []
    reachable = _downstream(graph, ingestion_id)
    nodes = []
    for node in graph.nodes:
        if node.id not in reachable:
            nodes.append(node)
            continue
        config = dict(node.config)
        if renamed:
            config = _rewrite_value(config, renamed)
        config["upstream_schema"] = schema
        nodes.append(node.model_copy(update={"config": config}))
    graph.nodes = nodes
    return graph


def _downstream(pipeline: Pipeline, start: str) -> set[str]:
    seen: set[str] = set()
    stack = [start]
    while stack:
        current = stack.pop()
        for edge in pipeline.outgoing(current):
            if edge.target not in seen:
                seen.add(edge.target)
                stack.append(edge.target)
    return seen
