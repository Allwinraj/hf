from __future__ import annotations

import re
from typing import Any

from app.engine.ast_sandbox import eval_expr
from app.models.pipeline import Pipeline
from app.models.run import Run, RunStep
from app.services.exporter import COLUMN_LABELS, present_row
from app.services.formulas import load_catalog
from app.services.insight import rows_of, to_number
from app.services.matching import get_bound

MATCHER_COLUMNS = {
    "status": "Matcher outcome for this pair (matched, residual, exception).",
    "confidence": "How strongly the matcher scored this pair.",
    "sources": "The source rows from each ingested file that were joined.",
    "keys": "Key values used to pair the rows.",
    "evidence": "Why the matcher treated these rows as the same item.",
    "residual": "Unapplied leftover after an allocation / split match.",
    "variance": "Numeric gap the matcher recorded between the paired amounts.",
    "direction": "Which side of a directional match this row sits on.",
    "allocation": "How a many-to-one payment was split across invoices.",
    "relationship": "Structural relationship the matcher assigned.",
}

DECISION_COLUMNS = {
    "verdict": "Decision outcome: approved, flagged, or escalated.",
    "confidence": "Decision confidence for this row.",
    "explanation": "Why this row received its verdict.",
    "remediation": "Suggested next action from the decision agent.",
    "policy_citation": "Policy document or section cited for this verdict.",
    "authority": "Who may clear this row (autonomous vs held for review).",
    "held_for_review": "Whether a human must review before release.",
    "mode": "Decision mode used for this row.",
    "risk_category": "Risk bucket assigned by policy.",
    "severity": "Severity assigned by policy.",
}


def substitute(expression: str, names: dict[str, Any]) -> str:
    if not expression:
        return ""
    rendered = expression
    for key, value in sorted(names.items(), key=lambda item: -len(str(item[0]))):
        if isinstance(value, (list, dict)):
            continue
        token = re.compile(rf"\b{re.escape(str(key))}\b")
        rendered = token.sub(_fmt(value), rendered)
    try:
        result = eval_expr(expression, names)
        return f"{rendered} = {_fmt(result)}"
    except Exception:
        return rendered


def _fmt(value: Any) -> str:
    num = to_number(value)
    if num is not None and not isinstance(value, bool):
        if abs(num - round(num)) < 1e-9:
            return str(int(round(num))) if abs(num) >= 100 else f"{num:.2f}".rstrip("0").rstrip(".")
        return f"{num:.2f}"
    if value is None:
        return "None"
    return str(value)


def _step_map(run: Run) -> dict[str, RunStep]:
    return {step.node_id: step for step in run.steps}


def _find_env(run: Run, node_id: str, port: str | None):
    step = _step_map(run).get(node_id)
    if not step:
        return None, None
    for env in step.outputs:
        if port is None or env.port == port:
            return step, env
    if step.outputs:
        return step, step.outputs[0]
    return step, None


def sheet_cards(pipeline: Pipeline, run: Run) -> list[dict[str, Any]]:
    cards = []
    by_id = pipeline.node_map()
    output_nodes = [n for n in pipeline.nodes if n.agent == "output"]
    source_ids = set()
    for node in output_nodes:
        for edge in pipeline.incoming(node.id):
            source_ids.add(edge.source)
    if not source_ids:
        source_ids = {step.node_id for step in run.steps if step.outputs}
    tabs: dict[str, Any] = {}
    for node in output_nodes:
        tabs.update(dict((node.config or {}).get("tabs") or {}))
    for step in run.steps:
        if step.node_id not in source_ids and step.agent == "ingestion":
            continue
        node = by_id.get(step.node_id)
        for env in step.outputs:
            rows = rows_of(env.payload or {})
            if env.payload and env.payload.get("kind") in {"artifacts", "knowledge"}:
                continue
            if not rows and env.port == "default" and step.agent == "output":
                continue
            columns = []
            for row in rows[:1]:
                columns = list(present_row(row).keys())
            name = str(tabs.get(env.port) or env.port)
            cards.append(
                {
                    "port": env.port,
                    "sheet_name": name,
                    "node_id": step.node_id,
                    "agent": step.agent,
                    "row_count": len(rows),
                    "purpose": _sheet_purpose(node, env.port, len(rows), pipeline),
                    "columns": columns,
                    "key_columns": list((node.config or {}).get("keys") or []) if node else [],
                    "computed_columns": _computed_columns(node),
                    "verdict_columns": [c for c in columns if c in DECISION_COLUMNS or c.startswith("verdict")],
                }
            )
    if not cards:
        for step in reversed(run.steps):
            for env in step.outputs:
                rows = rows_of(env.payload or {})
                if rows:
                    columns = list(present_row(rows[0]).keys())
                    cards.append(
                        {
                            "port": env.port,
                            "sheet_name": env.port,
                            "node_id": step.node_id,
                            "agent": step.agent,
                            "row_count": len(rows),
                            "purpose": f"{step.agent} emitted {len(rows)} row(s) on {env.port}.",
                            "columns": columns,
                            "key_columns": [],
                            "computed_columns": [],
                            "verdict_columns": [],
                        }
                    )
                    break
            if cards:
                break
    return cards


def _computed_columns(node) -> list[str]:
    if not node or node.agent != "math":
        return []
    col = (node.config or {}).get("output_column")
    return [str(col)] if col else []


def _sheet_purpose(node, port: str, count: int, pipeline: Pipeline) -> str:
    purpose = (pipeline.meta or {}).get("purpose") or pipeline.name or "this process"
    labels = {
        "matched": f"Rows that paired for {purpose} ({count}).",
        "residuals": f"Partial or leftover amounts after allocation ({count}).",
        "exceptions": f"Rows that did not clear {purpose} ({count}).",
        "approved": f"Rows approved for {purpose} ({count}).",
        "flagged": f"Rows flagged for review in {purpose} ({count}).",
        "escalated": f"Rows escalated from {purpose} ({count}).",
        "default": f"Working output from {node.label if node else 'the pipeline'} ({count} rows).",
    }
    return labels.get(port, labels["default"])


def column_lineage(pipeline: Pipeline, run: Run) -> list[dict[str, Any]]:
    catalog = load_catalog()
    known: dict[str, dict[str, Any]] = {}
    by_id = pipeline.node_map()
    for node in pipeline.nodes:
        step = _step_map(run).get(node.id)
        if not step:
            continue
        cfg = node.config or {}
        if node.agent == "ingestion":
            for env in step.outputs:
                schema = (env.payload or {}).get("schema") or cfg.get("schema") or []
                filename = cfg.get("filename") or ""
                sheet = (env.payload or {}).get("sheet")
                file_id = (env.payload or {}).get("file_id") or cfg.get("file_id")
                for col in schema:
                    name = str(col.get("name") or "")
                    if not name:
                        continue
                    known[name] = {
                        "column": name,
                        "origin": "source",
                        "file_id": file_id,
                        "filename": filename,
                        "sheet": sheet,
                        "source_name": col.get("source_name") or name,
                        "type": col.get("type"),
                        "samples": col.get("samples") or [],
                        "why": (
                            f"Read from `{filename or file_id}` column "
                            f"`{col.get('source_name') or name}`"
                            + (f" ({col.get('type')})" if col.get("type") else "")
                            + "."
                        ),
                    }
        if node.agent == "matcher":
            keys = [str(k) for k in (cfg.get("keys") or [])]
            for key in keys:
                prior = dict(known.get(key) or {"column": key, "origin": "match_key"})
                prior["origin"] = "match_key"
                prior["why"] = f"Used to pair rows; this row matched on {', '.join(keys)}."
                known[key] = prior
            for name, why in MATCHER_COLUMNS.items():
                known[name] = {"column": name, "origin": "match_meta", "why": why}
        if node.agent == "math":
            output = str(cfg.get("output_column") or (step.outputs[0].payload or {}).get("logic", {}).get("output") or "")
            logic = {}
            if step.outputs:
                logic = dict((step.outputs[0].payload or {}).get("logic") or {})
            catalog_id = cfg.get("catalog_id") or logic.get("catalog_id")
            description = ""
            try:
                if catalog_id:
                    description = catalog.get(str(catalog_id)).description
            except KeyError:
                description = ""
            input_map = dict(cfg.get("input_map") or logic.get("input_map") or {})
            bound = description or cfg.get("formula_en") or logic.get("ast") or "the compiled calculation"
            for canon, source in input_map.items():
                bound = bound.replace(canon, f"`{source}`")
            if output:
                known[output] = {
                    "column": output,
                    "origin": "computed",
                    "catalog_id": catalog_id,
                    "ast": cfg.get("ast") or logic.get("ast"),
                    "input_map": input_map,
                    "constants": cfg.get("constants") or logic.get("constants"),
                    "output_column": output,
                    "why": f"Computed as `{output}`: {bound}.",
                }
            known["flag"] = {
                "column": "flag",
                "origin": "computed",
                "why": "True when the math gate fired for this row.",
            }
        if node.agent == "decision":
            policy = cfg.get("policy") or "the review rules from the conversation"
            for name, why in DECISION_COLUMNS.items():
                extra = f" Policy: {policy}." if name in {"verdict", "explanation"} else ""
                known[name] = {"column": name, "origin": "verdict", "why": why + extra}

    columns: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for card in sheet_cards(pipeline, run):
        for col in card["columns"]:
            key = (card["node_id"], card["port"], col)
            if key in seen:
                continue
            seen.add(key)
            leaf = col.split(".")[-1]
            original = next((key for key, label in COLUMN_LABELS.items() if label == col and key in known), None)
            if original is None:
                original = next((key for key, label in COLUMN_LABELS.items() if label == col), leaf)
            meta = dict(known.get(col) or known.get(leaf) or known.get(original) or {})
            if not meta:
                meta = {
                    "column": col,
                    "origin": "passthrough",
                    "why": f"Carried through from upstream into `{card['sheet_name']}`.",
                }
            meta.update(
                {
                    "column": col,
                    "node_id": card["node_id"],
                    "port": card["port"],
                    "sheet_name": card["sheet_name"],
                }
            )
            columns.append(meta)
    return columns


def derivation_cards(pipeline: Pipeline, run: Run) -> list[dict[str, Any]]:
    by_id = pipeline.node_map()
    cards = []
    for node in pipeline.nodes:
        step = _step_map(run).get(node.id)
        cfg = node.config or {}
        incoming = []
        for edge in pipeline.incoming(node.id):
            src = _step_map(run).get(edge.source)
            count = 0
            if src:
                for env in src.outputs:
                    if env.port == edge.source_port or edge.source_port == "default":
                        count = len(rows_of(env.payload or {}))
                        break
            incoming.append({"port": edge.source_port, "from_node": edge.source, "row_count": count})
        outputs = []
        rows_out = 0
        if step:
            for env in step.outputs:
                rows = rows_of(env.payload or {})
                rows_out += len(rows)
                sample = [present_row(row) for row in rows[:3]]
                cols = list(sample[0].keys()) if sample else []
                outputs.append(
                    {
                        "port": env.port,
                        "row_count": len(rows),
                        "columns": cols,
                        "sample_rows": sample,
                    }
                )
        rows_in = sum(item["row_count"] for item in incoming)
        why = ""
        if step and step.skip_reason:
            why = f"Skipped: {step.skip_reason}"
        elif node.agent == "math":
            why = f"Applies: {cfg.get('formula_en') or cfg.get('catalog_id') or 'the compiled calculation'}."
        elif node.agent == "matcher":
            keys = cfg.get("keys") or []
            why = f"Pairs rows on {', '.join(str(k) for k in keys) or 'the named fields'}."
        elif node.agent == "decision":
            why = f"Flags or approves using: {cfg.get('policy') or 'the review rules'}."
        elif node.agent == "ingestion":
            why = f"Reads {cfg.get('filename') or node.label}."
        elif node.agent == "output":
            why = "Builds the downloadable report from upstream ports."
        cards.append(
            {
                "node_id": node.id,
                "agent": node.agent,
                "label": node.label or node.id,
                "mode": node.mode,
                "status": step.status if step else "pending",
                "purpose": why,
                "inputs": incoming,
                "logic": {
                    "catalog_id": cfg.get("catalog_id"),
                    "formula_en": cfg.get("formula_en"),
                    "ast": cfg.get("ast"),
                    "keys": cfg.get("keys"),
                    "policy": cfg.get("policy"),
                    "thresholds": cfg.get("constants") or cfg.get("confidence_threshold"),
                    "input_map": cfg.get("input_map"),
                    "output_column": cfg.get("output_column"),
                },
                "outputs": outputs,
                "numbers": {
                    "rows_in": rows_in,
                    "rows_out": rows_out,
                    "dropped": max(rows_in - rows_out, 0),
                    "matched_pct": round((rows_out / rows_in) * 100, 1) if rows_in else None,
                },
                "why": why,
            }
        )
    return cards


def _bind_names(row: dict[str, Any], input_map: dict[str, str], constants: dict[str, Any]) -> dict[str, Any]:
    names: dict[str, Any] = {}
    for key, value in row.items():
        num = to_number(value)
        names[key] = num if num is not None else value
    names.update(constants or {})
    for canon, source in (input_map or {}).items():
        raw = row.get(source)
        if raw is None and "." not in str(source):
            raw = _deep_get(row, source)
        num = to_number(raw)
        names[canon] = num if num is not None else raw
    return names


def _deep_get(row: dict[str, Any], name: str) -> Any:
    if name in row:
        return row[name]
    for key, value in row.items():
        if isinstance(value, dict):
            found = _deep_get(value, name)
            if found is not None:
                return found
    return None


def row_trace(pipeline: Pipeline, run: Run, node_id: str, port: str, row_index: int) -> dict[str, Any]:
    step, env = _find_env(run, node_id, port)
    if not env:
        return {"row": {}, "steps": [], "error": "envelope not found"}
    rows = rows_of(env.payload or {})
    if row_index < 0 or row_index >= len(rows):
        return {"row": {}, "steps": [], "error": "row index out of range"}
    row = rows[row_index]
    stages: list[dict[str, Any]] = []
    source = row.get("source") if isinstance(row.get("source"), dict) else row
    nested_sources = source.get("sources") if isinstance(source, dict) else None
    if isinstance(nested_sources, dict):
        stages.append(
            {
                "stage": "ingested",
                "from": [{"file_id": key, "row": value} for key, value in nested_sources.items()],
            }
        )
    elif row.get("sources") and isinstance(row.get("sources"), dict):
        stages.append(
            {
                "stage": "ingested",
                "from": [{"file_id": key, "row": value} for key, value in row["sources"].items()],
            }
        )

    keys = source.get("keys") if isinstance(source, dict) else row.get("keys")
    evidence = source.get("evidence") if isinstance(source, dict) else row.get("evidence")
    confidence = source.get("confidence") if isinstance(source, dict) else row.get("confidence")
    if keys or evidence:
        stages.append(
            {
                "stage": "matched",
                "keys": keys,
                "evidence": evidence,
                "confidence": confidence,
                "why": _match_why(pipeline, keys, evidence, confidence),
            }
        )

    math_node = next((n for n in pipeline.nodes if n.agent == "math"), None)
    if math_node:
        cfg = math_node.config or {}
        math_step = _step_map(run).get(math_node.id)
        logic = {}
        math_rows: list[dict[str, Any]] = []
        if math_step and math_step.outputs:
            logic = dict((math_step.outputs[0].payload or {}).get("logic") or {})
            math_rows = rows_of(math_step.outputs[0].payload or {})
        input_map = dict(cfg.get("input_map") or logic.get("input_map") or {})
        constants = dict(cfg.get("constants") or logic.get("constants") or {})
        ast = str(cfg.get("ast") or logic.get("ast") or "")
        gate_ast = cfg.get("gate_ast") or logic.get("gate_ast")
        output = str(cfg.get("output_column") or logic.get("output") or "")
        bind_row = source if isinstance(source, dict) else row
        if node_id == math_node.id and math_rows and 0 <= row_index < len(math_rows):
            bind_row = math_rows[row_index]
        names = _bind_names(bind_row, input_map, constants)
        if str(logic.get("shape") or cfg.get("shape")) == "sequential" and math_rows and node_id == math_node.id:
            names = _replay_sequential(math_rows, row_index, input_map, constants, output, ast, names)
        computed = {
            "stage": "computed",
            "output_column": output,
            "expression": ast,
            "substituted": substitute(ast, names) if ast else "",
            "why": cfg.get("formula_en") or logic.get("catalog_id") or "compiled calculation",
        }
        if gate_ast:
            try:
                gate_val = bool(eval_expr(str(gate_ast), names))
            except Exception:
                gate_val = None
            computed["gate"] = f"{substitute(str(gate_ast), names)} -> {gate_val}"
        if output and (output in row or output in bind_row):
            computed["value"] = row.get(output, bind_row.get(output))
        stages.append(computed)

    verdict = row.get("verdict")
    explanation = row.get("explanation")
    if verdict or explanation:
        stages.append(
            {
                "stage": "decided",
                "verdict": verdict,
                "explanation": explanation,
                "citation": row.get("policy_citation"),
                "confidence": row.get("confidence"),
                "why": explanation or (f"Verdict {verdict}." if verdict else ""),
            }
        )
    justification = _justification_lines(row, stages)
    return {
        "row": present_row(row) if isinstance(row, dict) else {"value": row},
        "row_index": row_index,
        "node_id": node_id,
        "port": port,
        "steps": stages,
        "justification": justification,
    }


def _replay_sequential(
    rows: list[dict[str, Any]],
    row_index: int,
    input_map: dict[str, str],
    constants: dict[str, Any],
    output: str,
    ast: str,
    names: dict[str, Any],
) -> dict[str, Any]:
    previous = 0.0
    last = names
    for index, row in enumerate(rows[: row_index + 1]):
        last = _bind_names(row, input_map, constants)
        last["previous"] = previous
        if ast:
            try:
                previous = float(eval_expr(ast, last) or 0)
            except Exception:
                previous = to_number(row.get(output)) or previous
        else:
            previous = to_number(row.get(output)) or previous
        if index == row_index:
            return last
    return last


def _match_why(pipeline: Pipeline, keys: Any, evidence: Any, confidence: Any) -> str:
    matcher = next((n for n in pipeline.nodes if n.agent == "matcher"), None)
    named = []
    if matcher:
        named = list((matcher.config or {}).get("keys") or [])
    window = (matcher.config or {}).get("window_days") if matcher else None
    parts = []
    if named:
        parts.append(f"Paired on {', '.join(str(k) for k in named)}")
    elif keys:
        if isinstance(keys, dict):
            parts.append("Paired on " + ", ".join(f"{k}={v}" for k, v in keys.items()))
        else:
            parts.append(f"Paired on {keys}")
    if window not in (None, ""):
        parts.append(f"within a {window} day window")
    if confidence not in (None, ""):
        parts.append(f"confidence {confidence}")
    kind = None
    if isinstance(evidence, list) and evidence and isinstance(evidence[0], dict):
        kind = evidence[0].get("type")
    if kind:
        parts.append(f"{kind} match")
    return ". ".join(str(p) for p in parts) + "." if parts else "Matcher recorded this pair."


def _pick(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = get_bound(row, name)
        if value in (None, ""):
            value = row.get(name)
        if value not in (None, ""):
            return value
    return None


def _justification_lines(row: dict[str, Any], stages: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    matched = next((item for item in stages if item.get("stage") == "matched"), None)
    computed = next((item for item in stages if item.get("stage") == "computed"), None)
    decided = next((item for item in stages if item.get("stage") == "decided"), None)
    ident = _pick(row, "invoice_number")
    party = _pick(row, "customer_name", "payer_name_on_bank", "payer_name")
    outcome = _pick(row, "payment_outcome")
    received = _pick(row, "amount_received", "amount")
    expected = _pick(row, "invoice_total", "total_amount")

    if ident or party or outcome or (matched and matched.get("why")):
        subject = " ".join(part for part in (str(ident) if ident else "", str(party) if party else "") if part).strip()
        if outcome and subject:
            lines.append(f"{subject} was treated as {outcome}.")
        elif outcome:
            lines.append(f"This row was treated as {outcome}.")
        elif matched and matched.get("why"):
            lines.append(str(matched["why"]))
        elif subject:
            lines.append(f"{subject} was paired from the source files.")

    if computed:
        if computed.get("substituted"):
            lines.append(f"Calculation: {computed['substituted']}.")
        elif computed.get("why"):
            lines.append(f"Calculation used {computed['why']}.")
        if computed.get("gate"):
            lines.append(f"Tolerance check: {computed['gate']}.")
        elif received is not None and expected is not None:
            lines.append(f"Amount received {received} was compared with expected {expected}.")

    if decided:
        verdict = decided.get("verdict")
        explanation = decided.get("explanation")
        if verdict and explanation:
            lines.append(f"Decision: {verdict} — {explanation}")
        elif explanation:
            lines.append(str(explanation))
        elif verdict:
            lines.append(f"Decision: {verdict}.")
    elif row.get("flag") is True:
        lines.append("Math flagged this row as outside the configured tolerance.")
    elif row.get("flag") is False:
        lines.append("The amount is inside the configured tolerance.")

    unique: list[str] = []
    for line in lines:
        text = " ".join(str(line).split())
        if text and text not in unique:
            unique.append(text)
    if len(unique) > 3:
        unique = [unique[0], unique[1], unique[-1]]
    return unique[:3]


def sheet_rows(
    run: Run,
    node_id: str,
    port: str,
    *,
    offset: int = 0,
    limit: int = 50,
    only_exceptions: bool = False,
) -> dict[str, Any]:
    step, env = _find_env(run, node_id, port)
    if not env:
        return {"columns": [], "rows": [], "total": 0, "offset": offset, "limit": limit}
    raw = rows_of(env.payload or {})
    if only_exceptions:
        raw = [
            row
            for row in raw
            if str(row.get("verdict") or row.get("status") or env.port)
            in {"exceptions", "flagged", "escalated", "unmatched", "error"}
            or env.port in {"exceptions", "flagged", "escalated", "residuals"}
        ]
    flat = [present_row(row) if isinstance(row, dict) else {"value": row} for row in raw]
    columns: list[str] = []
    for row in flat[:30]:
        for key in row:
            if key not in columns:
                columns.append(key)
    sliced = flat[offset : offset + max(1, min(limit, 200))]
    indexed = []
    for i, row in enumerate(sliced):
        item = dict(row)
        item["_row_index"] = offset + i
        indexed.append(item)
    return {
        "columns": columns,
        "rows": indexed,
        "total": len(flat),
        "offset": offset,
        "limit": limit,
        "node_id": node_id,
        "port": port,
        "agent": step.agent if step else None,
    }
