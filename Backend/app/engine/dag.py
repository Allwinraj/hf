from __future__ import annotations

from collections import defaultdict, deque

from app.models.pipeline import Pipeline


class DagError(ValueError):
    """Pipeline graph is invalid."""


def topological_levels(pipeline: Pipeline) -> list[list[str]]:
    """Return node ids grouped into concurrent-ready levels (Kahn)."""
    ids = [node.id for node in pipeline.nodes]
    incoming: dict[str, int] = {nid: 0 for nid in ids}
    children: dict[str, list[str]] = defaultdict(list)
    for edge in pipeline.edges:
        if edge.source not in incoming or edge.target not in incoming:
            raise DagError(f"edge {edge.id} references unknown node")
        incoming[edge.target] += 1
        children[edge.source].append(edge.target)

    ready = deque(nid for nid, count in incoming.items() if count == 0)
    seen = 0
    levels: list[list[str]] = []
    remaining = dict(incoming)

    while ready:
        level = list(ready)
        ready.clear()
        levels.append(level)
        for nid in level:
            seen += 1
            for child in children[nid]:
                remaining[child] -= 1
                if remaining[child] == 0:
                    ready.append(child)

    if seen != len(ids):
        raise DagError("pipeline contains a cycle")
    return levels


def predecessors(pipeline: Pipeline, node_id: str) -> list[str]:
    return [edge.source for edge in pipeline.incoming(node_id)]
