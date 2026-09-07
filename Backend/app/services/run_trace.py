from __future__ import annotations

from typing import Any

from app.engine.conditional import edge_accepts
from app.models.envelope import Envelope
from app.models.pipeline import Node, Pipeline
from app.models.run import RunStep
from app.services.exporter import format_output_label, resolve_output_formats


def envelope_row_count(env: Envelope) -> int:
    payload = env.payload or {}
    rows = payload.get("rows")
    if isinstance(rows, list):
        return len(rows)
    return 0


def port_counts(envelopes: list[Envelope]) -> dict[str, int]:
    out: dict[str, int] = {}
    for env in envelopes:
        out[env.port] = out.get(env.port, 0) + envelope_row_count(env)
    return out


def thinking_line(node: Node) -> str:
    cfg = node.config or {}
    agent = node.agent
    label = node.label or agent
    if agent == "ingestion":
        name = cfg.get("filename") or cfg.get("file_id") or label
        return f"Loading {name}"
    if agent == "matcher":
        keys = cfg.get("keys") or cfg.get("match_keys") or []
        key_text = " + ".join(str(k) for k in keys) if keys else "configured keys"
        window = cfg.get("window_days")
        if window in (None, "", "None") and isinstance(cfg.get("window"), dict):
            window = cfg["window"].get("days")
        extra = f" (±{window} days)" if window not in (None, "", "None") else ""
        return f"Matching on {key_text}{extra}"
    if agent == "math":
        formula = cfg.get("formula_en") or cfg.get("catalog_id") or cfg.get("ast") or "the formula"
        return f"Calculating {formula}"
    if agent == "decision":
        return "Applying review rules"
    if agent == "output":
        formats = resolve_output_formats(cfg, node_mode=node.mode)
        return f"Writing {format_output_label(formats)}"
    return f"Running {label}"


def describe_skip(
    pipeline: Pipeline,
    node: Node,
    outputs_by_node: dict[str, list[Envelope]],
) -> str:
    bits: list[str] = []
    for edge in pipeline.incoming(node.id):
        produced = outputs_by_node.get(edge.source, [])
        accepted = [env for env in produced if edge_accepts(edge, env)]
        if accepted:
            continue
        src = pipeline.get_node(edge.source)
        src_label = src.label or src.agent
        others = []
        for env in produced:
            count = envelope_row_count(env)
            others.append(f"{count} {env.port}")
        wanted = edge.source_port
        if others:
            bits.append(
                f"No rows from {src_label} on '{wanted}' ({', '.join(others)})."
            )
        else:
            bits.append(f"{src_label} produced nothing for '{wanted}'.")
    if not bits:
        return "No input from upstream agents."
    if node.agent == "math":
        return bits[0].replace("No rows from", "No matched rows from").replace(
            " on 'matched'", ""
        ) if "matched" in bits[0] else bits[0] + " Calculation did not run."
    return " ".join(bits)


def summarize_step(pipeline: Pipeline, step: RunStep) -> str:
    node = pipeline.get_node(step.node_id)
    label = node.label or node.agent.title()
    cfg = node.config or {}
    ms = _fmt_ms(step.duration_ms)
    if step.status == "skipped":
        reason = step.skip_reason or "No input from upstream agents."
        return f"{label} — skipped. {reason}"
    if step.status == "error":
        return f"{label} — error. {step.error or 'failed'} ({ms})"
    counts = port_counts(step.outputs)
    if node.agent == "ingestion":
        name = cfg.get("filename") or cfg.get("file_id") or label
        rows = sum(counts.values())
        return f"{label} — loaded {rows} rows from {name} ({ms})"
    if node.agent == "matcher":
        keys = cfg.get("keys") or []
        key_text = " + ".join(str(k) for k in keys) if keys else "configured keys"
        window = cfg.get("window_days")
        if window in (None, "", "None") and isinstance(cfg.get("window"), dict):
            window = cfg["window"].get("days")
        extra = f" (±{window} days)" if window not in (None, "", "None") else ""
        matched = counts.get("matched", 0)
        exceptions = counts.get("exceptions", 0)
        residuals = counts.get("residuals", 0)
        return (
            f"{label} — paired on {key_text}{extra}. "
            f"{matched} matched, {exceptions} exceptions"
            + (f", {residuals} residuals" if residuals else "")
            + f" ({ms})"
        )
    if node.agent == "math":
        formula = cfg.get("formula_en") or cfg.get("catalog_id") or "formula"
        rows = sum(counts.values())
        flags = 0
        for env in step.outputs:
            for row in env.payload.get("rows") or []:
                if isinstance(row, dict) and row.get("flag") is True:
                    flags += 1
        flag_bit = f", {flags} flags" if flags else ""
        return f"{label} — {formula} on {rows} lines{flag_bit} ({ms})"
    if node.agent == "decision":
        approved = counts.get("approved", 0)
        flagged = counts.get("flagged", 0)
        escalated = counts.get("escalated", 0)
        return (
            f"{label} — {approved} approved, {flagged} flagged, {escalated} escalated ({ms})"
        )
    if node.agent == "output":
        artifacts: list[str] = []
        for env in step.outputs:
            for name in env.payload.get("artifacts") or []:
                artifacts.append(str(name).rsplit("\\", 1)[-1].rsplit("/", 1)[-1])
        names = ", ".join(artifacts) if artifacts else format_output_label(
            resolve_output_formats(cfg, node_mode=node.mode)
        )
        return f"{label} — wrote {names} ({ms})"
    total = sum(counts.values())
    return f"{label} — completed ({total} rows, {ms})"


def node_log_fields(pipeline: Pipeline, node: Node, step: RunStep) -> dict[str, Any]:
    filename = (node.config or {}).get("filename") or ""
    rows = sum(port_counts(step.outputs).values())
    return {
        "pipeline": pipeline.id,
        "run": step.node_id,
        "node": node.id,
        "agent": node.agent,
        "status": step.status,
        "rows": rows,
        "file": filename,
        "ms": int(step.duration_ms),
        "skip": step.skip_reason or "",
        "error": step.error or "",
    }


def format_console_line(pipeline: Pipeline, run_id: str, node: Node, step: RunStep) -> str:
    filename = (node.config or {}).get("filename") or "-"
    rows = sum(port_counts(step.outputs).values())
    skip = f" skip={step.skip_reason}" if step.skip_reason else ""
    err = f" error={step.error}" if step.error else ""
    return (
        f"pipeline={pipeline.id} run={run_id} node={node.id} agent={node.agent} "
        f"status={step.status} rows={rows} file={filename} ms={int(step.duration_ms)}"
        f"{skip}{err}"
    )


def _fmt_ms(value: float) -> str:
    if value >= 1000:
        return f"{value / 1000:.1f}s"
    return f"{int(value)}ms"
