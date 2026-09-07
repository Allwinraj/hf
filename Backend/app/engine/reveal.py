from __future__ import annotations

from copy import deepcopy

from app.models.chat import ConfigPatch, ProgressiveReveal
from app.models.pipeline import Edge, Node, Pipeline


def apply_reveal(pipeline: Pipeline, delta: ProgressiveReveal) -> Pipeline:
    """Incremental graph update. Never replaces the whole DAG."""
    graph = pipeline.model_copy(deep=True)
    nodes = {node.id: node for node in graph.nodes}
    edges = {edge.id: edge for edge in graph.edges}

    for node_id in delta.remove_node_ids:
        nodes.pop(node_id, None)
        edges = {
            eid: edge
            for eid, edge in edges.items()
            if edge.source != node_id and edge.target != node_id
        }

    for edge_id in delta.remove_edge_ids:
        edges.pop(edge_id, None)

    for node in delta.upsert_nodes:
        existing = nodes.get(node.id)
        if existing is None:
            nodes[node.id] = node
        else:
            merged = existing.model_copy(update=node.model_dump(exclude_unset=True))
            merged.config = {**existing.config, **node.config}
            nodes[node.id] = merged

    for edge in delta.upsert_edges:
        edges[edge.id] = edge

    for patch in delta.config_patches:
        node = nodes.get(patch.node_id)
        if node is None:
            continue
        node.config = _deep_merge(node.config, patch.config)

    graph.nodes = list(nodes.values())
    graph.edges = list(edges.values())
    return graph


def _deep_merge(base: dict, patch: dict) -> dict:
    out = deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = deepcopy(value)
    return out
