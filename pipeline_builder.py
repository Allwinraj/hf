from __future__ import annotations

from app.models.chat import ConfigPatch, ExtractedRequirement, InterviewSession, ProgressiveReveal
from app.models.pipeline import Edge, Node, Pipeline, Port
from app.services.exporter import output_mode_from_formats, resolve_output_formats
from app.services.formulas import hydrate_math_config, math_phrase_from_session
from app.services.mailbox_defaults import mailbox_config
from app.services.sessions import session_pipeline

MATCH_KINDS = {"match", "matcher", "join", "keys"}
MATH_KINDS = {"math", "formula", "gate", "variance"}
DECISION_KINDS = {"decision", "policy", "approval", "anomaly"}
OUTPUT_KINDS = {"output", "excel", "pdf", "export"}


def capabilities_from(session: InterviewSession) -> dict[str, object]:
    kinds = {r.kind.lower() for r in session.requirements}
    inferred = {
        "matcher": any(k in MATCH_KINDS for k in kinds),
        "math": any(k in MATH_KINDS for k in kinds),
        "decision": any(k in DECISION_KINDS for k in kinds),
        "output": any(k in OUTPUT_KINDS for k in kinds),
        "matcher_stages": 1,
        "math_stages": 1,
        "output_formats": ["xlsx"],
    }
    overlay = dict(session.extra.get("capabilities") or {})
    inferred.update(overlay)
    mailbox = bool(session.extra.get("mailbox_journey")) or any(
        str(u.get("name") or u.get("path") or "").lower().endswith(".eml")
        for u in session.uploads
        if u.get("kind") == "data"
    )
    if mailbox:
        inferred["matcher"] = False
        inferred["math"] = False
        inferred["decision"] = True
        inferred["output"] = True
        inferred["matcher_stages"] = 0
        inferred["math_stages"] = 0
        inferred.setdefault("output_formats", ["xlsx"])
    if "output" not in overlay and (inferred["matcher"] or inferred["math"] or inferred["decision"]):
        inferred["output"] = True
    return inferred


def desired_pipeline(session: InterviewSession) -> Pipeline:
    caps = capabilities_from(session)
    data_files = [u for u in session.uploads if u.get("kind") == "data"]
    knowledge_files = [u for u in session.uploads if u.get("kind") == "knowledge"]
    virtual_sources = list(session.extra.get("virtual_sources") or [])
    nodes: list[Node] = []
    edges: list[Edge] = []

    data_ids: list[str] = []
    for upload in data_files:
        nid = f"ingest_{upload['file_id']}"
        data_ids.append(nid)
        name = str(upload.get("name") or upload.get("path") or "")
        if name.lower().endswith(".eml"):
            config = mailbox_config(
                {
                    "sample_path": upload.get("path"),
                    "file_id": upload["file_id"],
                    "filename": upload.get("name") or upload["file_id"],
                    "send_details": session.extra.get("send_details") or "",
                }
            )
            nodes.append(
                Node(
                    id=nid,
                    agent="ingestion",
                    mode="mailbox",
                    label=str(upload.get("label") or "Mailbox"),
                    config=config,
                    ports=[Port(name="default")],
                )
            )
            continue
        nodes.append(
            Node(
                id=nid,
                agent="ingestion",
                mode="data",
                label=str(upload.get("label") or upload.get("name") or upload["file_id"]),
                config={
                    "mode": "data",
                    "path": upload["path"],
                    "file_id": upload["file_id"],
                    "filename": upload.get("name") or upload["file_id"],
                    "schema": upload.get("schema") or [],
                    "use_llm_schema": False,
                },
                ports=[Port(name="default")],
            )
        )

    for i, src in enumerate(virtual_sources):
        nid = f"ingest_virtual_{i + 1}"
        label = str(src.get("label") or f"Source {i + 1}")
        schema = list(src.get("columns") or src.get("schema") or [])
        data_ids.append(nid)
        nodes.append(
            Node(
                id=nid,
                agent="ingestion",
                mode="data",
                label=label,
                config={
                    "mode": "data",
                    "virtual": True,
                    "description": str(src.get("description") or ""),
                    "schema": schema,
                },
                ports=[Port(name="default")],
            )
        )

    knowledge_ids: list[str] = []
    for upload in knowledge_files:
        nid = f"ingest_knowledge_{upload['file_id']}"
        knowledge_ids.append(nid)
        nodes.append(
            Node(
                id=nid,
                agent="ingestion",
                mode="knowledge",
                label=str(upload.get("label") or upload.get("name") or upload["file_id"]),
                config={
                    "mode": "knowledge",
                    "path": upload["path"],
                    "file_id": upload["file_id"],
                    "filename": upload.get("name") or upload["file_id"],
                    "session_id": session.id,
                },
                ports=[Port(name="default")],
            )
        )

    cursor_ids = list(data_ids)
    cursor_port = "default"
    side_edges: list[tuple[str, str]] = []

    matcher_stages = int(caps.get("matcher_stages") or 1) if caps.get("matcher") else 0
    match_cfgs = _req_values(session.requirements, MATCH_KINDS)
    for i in range(matcher_stages):
        match_cfg = match_cfgs[i] if i < len(match_cfgs) else (match_cfgs[-1] if match_cfgs else {})
        nid = "matcher" if matcher_stages == 1 else f"matcher_{i + 1}"
        keys = list(match_cfg.get("keys") or caps.get("keys") or [])
        nodes.append(
            Node(
                id=nid,
                agent="matcher",
                mode=str(match_cfg.get("mode") or "structural"),
                label=str(match_cfg.get("label") or "Matcher"),
                config={
                    "mode": str(match_cfg.get("mode") or "structural"),
                    "keys": keys,
                    "flags": dict(match_cfg.get("flags") or {}),
                    "window_days": match_cfg.get("window_days"),
                    "window": (
                        {"days": int(match_cfg["window_days"])}
                        if str(match_cfg.get("window_days") or "").strip() not in {"", "None"}
                        else dict(match_cfg.get("window") or {})
                    ),
                },
                ports=[
                    Port(name="matched"),
                    Port(name="residuals"),
                    Port(name="exceptions"),
                ],
            )
        )
        for source in cursor_ids:
            edges.append(_edge(source, nid, source_port=cursor_port if source not in data_ids else "default"))
        if i == 0:
            for kid in knowledge_ids:
                edges.append(_edge(kid, nid))
        cursor_ids = [nid]
        cursor_port = "matched"
        side_edges.extend([(nid, "exceptions"), (nid, "residuals")])

    math_stages = int(caps.get("math_stages") or 1) if caps.get("math") else 0
    math_cfgs = _req_values(session.requirements, MATH_KINDS)
    for i in range(math_stages):
        math_cfg = math_cfgs[i] if i < len(math_cfgs) else (math_cfgs[-1] if math_cfgs else {})
        nid = "math" if math_stages == 1 else f"math_{i + 1}"
        config = {
            "mode": str(math_cfg.get("mode") or "calculation"),
            "shape": str(math_cfg.get("shape") or "per_row"),
        }
        if math_cfg.get("output_column"):
            config["output_column"] = math_cfg["output_column"]
        if math_cfg.get("catalog_id"):
            config["catalog_id"] = math_cfg["catalog_id"]
        if math_cfg.get("ast"):
            config["ast"] = math_cfg["ast"]
        if math_cfg.get("formula_en"):
            config["formula_en"] = math_cfg["formula_en"]
        if math_cfg.get("input_map"):
            config["input_map"] = math_cfg["input_map"]
        if math_cfg.get("threshold") is not None:
            config["threshold"] = math_cfg["threshold"]
        if math_cfg.get("gate_ast"):
            config["gate_ast"] = math_cfg["gate_ast"]
        constants = dict(math_cfg.get("constants") or {})
        if math_cfg.get("threshold") is not None and "amount" not in constants:
            constants.setdefault("amount", math_cfg["threshold"])
        if math_cfg.get("pct") is not None:
            constants.setdefault("pct", math_cfg["pct"])
        if constants:
            config["constants"] = constants
        if math_cfg.get("compiled_from"):
            config["compiled_from"] = math_cfg["compiled_from"]
        if not config.get("formula_en") and not config.get("catalog_id"):
            phrase = math_phrase_from_session(session)
            if phrase:
                config["formula_en"] = phrase
        config = hydrate_math_config(config)
        if not config.get("ast"):
            phrase = math_phrase_from_session(session)
            if phrase:
                config = hydrate_math_config({**config, "formula_en": phrase})
        formula_text = str(config.get("formula_en") or math_cfg.get("formula_en") or "")
        sequential = str(config.get("shape") or "").lower() == "sequential" or any(
            token in formula_text.lower()
            for token in ("running", "previous plus", "deposit", "withdrawal", "running balance")
        )
        if sequential:
            config["shape"] = "sequential"
        nodes.append(
            Node(
                id=nid,
                agent="math",
                mode=config["mode"],
                label=str(math_cfg.get("label") or "Math"),
                config=config,
                ports=[Port(name="default")],
            )
        )
        for source in cursor_ids:
            _add_edge(edges, source, nid, source_port=cursor_port)
        if sequential:
            for did in data_ids:
                _add_edge(edges, did, nid)
        cursor_ids = [nid]
        cursor_port = "default"

    if caps.get("decision"):
        dec_cfg = _req_value(session.requirements, DECISION_KINDS)
        nodes.append(
            Node(
                id="decision",
                agent="decision",
                mode=str(dec_cfg.get("mode") or "approval"),
                label=str(dec_cfg.get("label") or "Decision"),
                config={
                    "mode": str(dec_cfg.get("mode") or "approval"),
                    "authority": str(dec_cfg.get("authority") or "autonomous"),
                    "confidence_threshold": float(dec_cfg.get("confidence_threshold") or 0.85),
                    "policy": str(dec_cfg.get("policy") or ""),
                },
                ports=[
                    Port(name="approved"),
                    Port(name="flagged"),
                    Port(name="escalated"),
                ],
            )
        )
        for source in cursor_ids:
            edges.append(_edge(source, "decision", source_port=cursor_port))
        for sid, port in side_edges:
            edges.append(_edge(sid, "decision", source_port=port))
        for kid in knowledge_ids:
            edges.append(_edge(kid, "decision"))
        cursor_ids = ["decision"]
        side_edges = [("decision", "approved"), ("decision", "flagged"), ("decision", "escalated")]
        cursor_port = "approved"
    elif knowledge_ids:
        pass

    if caps.get("output") and (cursor_ids or side_edges):
        out_cfg = _req_value(session.requirements, OUTPUT_KINDS)
        req_formats = list(out_cfg.get("formats") or [])
        cap_formats = list(caps.get("output_formats") or [])
        formats = resolve_output_formats(
            {
                "mode": out_cfg.get("mode") or "",
                "formats": req_formats or cap_formats,
            }
        )
        mode = output_mode_from_formats(formats)
        nodes.append(
            Node(
                id="output",
                agent="output",
                mode=mode,
                label=str(out_cfg.get("label") or "Output"),
                config={
                    "mode": mode,
                    "formats": formats,
                    "theme": str(out_cfg.get("theme") or "executive_classic"),
                    "title": str(out_cfg.get("title") or "Nexus Report"),
                },
                ports=[Port(name="default")],
            )
        )
        if caps.get("decision"):
            for sid, port in side_edges:
                edges.append(_edge(sid, "output", source_port=port))
        else:
            for source in cursor_ids:
                edges.append(_edge(source, "output", source_port=cursor_port))
            for sid, port in side_edges:
                edges.append(_edge(sid, "output", source_port=port))

    nodes = _apply_overrides(nodes, session.extra.get("node_overrides") or {})
    return Pipeline(id=session.id, name="draft", version="0.1", nodes=nodes, edges=edges)


def diff_reveal(current: Pipeline, desired: Pipeline) -> ProgressiveReveal:
    cur_nodes = current.node_map()
    des_nodes = desired.node_map()
    remove_node_ids = [nid for nid in cur_nodes if nid not in des_nodes]
    upsert_nodes = []
    patches: list[ConfigPatch] = []
    for nid, node in des_nodes.items():
        existing = cur_nodes.get(nid)
        if existing is None:
            upsert_nodes.append(node)
            continue
        if (
            existing.agent != node.agent
            or existing.mode != node.mode
            or existing.label != node.label
            or existing.ports != node.ports
        ):
            upsert_nodes.append(node)
        elif existing.config != node.config:
            patches.append(ConfigPatch(node_id=nid, config=node.config))

    cur_edges = {e.id: e for e in current.edges}
    des_edges = {e.id: e for e in desired.edges}
    remove_edge_ids = [eid for eid in cur_edges if eid not in des_edges]
    upsert_edges = [
        edge
        for eid, edge in des_edges.items()
        if eid not in cur_edges or cur_edges[eid] != edge
    ]
    return ProgressiveReveal(
        upsert_nodes=upsert_nodes,
        remove_node_ids=remove_node_ids,
        upsert_edges=upsert_edges,
        remove_edge_ids=remove_edge_ids,
        config_patches=patches,
    )


def reveal_for_session(session: InterviewSession) -> ProgressiveReveal:
    current = session_pipeline(session)
    desired = desired_pipeline(session)
    return diff_reveal(current, desired)


def reveal_is_empty(delta: ProgressiveReveal) -> bool:
    return not (
        delta.upsert_nodes
        or delta.remove_node_ids
        or delta.upsert_edges
        or delta.remove_edge_ids
        or delta.config_patches
    )


def _apply_overrides(nodes: list[Node], overrides: dict) -> list[Node]:
    out = []
    for node in nodes:
        patch = overrides.get(node.id)
        if not patch:
            out.append(node)
            continue
        config = {**node.config, **patch}
        updates: dict = {"config": config}
        if node.agent == "output":
            formats = resolve_output_formats(config, node_mode=str(config.get("mode") or node.mode))
            config["formats"] = formats
            config["mode"] = output_mode_from_formats(formats)
            updates["config"] = config
            updates["mode"] = config["mode"]
        out.append(node.model_copy(update=updates))
    return out


def _req_value(requirements: list[ExtractedRequirement], kinds: set[str]) -> dict:
    values = _req_values(requirements, kinds)
    return values[-1] if values else {}


def _req_values(requirements: list[ExtractedRequirement], kinds: set[str]) -> list[dict]:
    return [dict(req.value or {}) for req in requirements if req.kind.lower() in kinds]


def _edge(source: str, target: str, *, source_port: str = "default") -> Edge:
    return Edge(
        id=f"e_{source}_{source_port}_{target}",
        source=source,
        source_port=source_port,
        target=target,
    )


def _add_edge(edges: list[Edge], source: str, target: str, *, source_port: str = "default") -> None:
    edge = _edge(source, target, source_port=source_port)
    key = (edge.source, edge.source_port, edge.target)
    if any((e.source, e.source_port, e.target) == key for e in edges):
        return
    edges.append(edge)
