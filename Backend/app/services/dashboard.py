from __future__ import annotations

import json
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.core.llm import LLMError, LLMProvider
from app.core.settings import BACKEND_ROOT
from app.models.pipeline import Pipeline
from app.models.run import Run
from app.services.insight import (
    column_stats,
    date_columns,
    group_sum,
    narrate,
    rate,
    rows_of,
    sparkline,
    timeseries,
    to_number,
    use_case_profile,
    variance,
)

CATALOG_IDS = {
    "kpi_card",
    "bar_chart",
    "pie_chart",
    "donut_chart",
    "line_chart",
    "grouped_bar_chart",
    "stacked_bar_chart",
    "variance_chart",
    "area_chart",
    "insight_table",
    "breakdown_table",
    "exception_table",
    "rate_gauge",
    "narrative_card",
    "action_list",
    "mail_reply_table",
}

SELECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["widgets"],
    "properties": {
        "widgets": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["catalog_id"],
                "properties": {
                    "catalog_id": {"type": "string"},
                    "title": {"type": "string"},
                    "source_node": {"type": "string"},
                    "source_port": {"type": "string"},
                    "field_map": {"type": "object"},
                    "limit": {"type": "integer"},
                },
            },
        }
    },
}


@lru_cache
def catalog_digest() -> str:
    path = BACKEND_ROOT / "data" / "dashboards" / "v1.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    lines = []
    for item in data.get("widgets") or []:
        lines.append(f"{item.get('id')}: {item.get('description')}")
    return "\n".join(lines)


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("rows")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    return []


def _is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value.replace(",", ""))
            return True
        except ValueError:
            return False
    return False


def _to_number(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return float(str(value).replace(",", ""))


def port_summaries(run: Run) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for step in run.steps:
        for env in step.outputs:
            rows = _rows(env.payload or {})
            columns: list[str] = []
            for row in rows[:30]:
                for key in row:
                    if key not in columns:
                        columns.append(str(key))
            numeric: list[str] = []
            categorical: list[str] = []
            sample = rows[:20]
            for col in columns:
                values = [row.get(col) for row in sample if col in row]
                if values and all(_is_number(v) or v in (None, "") for v in values) and any(_is_number(v) for v in values):
                    numeric.append(col)
                else:
                    categorical.append(col)
            stats = {col: column_stats(rows, col) for col in numeric[:12]}
            summaries.append(
                {
                    "node_id": step.node_id,
                    "agent": step.agent,
                    "port": env.port,
                    "row_count": len(rows),
                    "columns": columns[:24],
                    "numeric": numeric[:12],
                    "categorical": categorical[:12],
                    "date_columns": date_columns(rows, columns)[:8],
                    "sample_rows": rows[:3],
                    "stats": stats,
                    "status": step.status,
                    "summary": step.summary,
                }
            )
    return summaries


def ground_specs(
    specs: list[dict[str, Any]],
    ports: list[dict[str, Any]],
    allowed_ids: set[str],
) -> list[dict[str, Any]]:
    """Drop anything an LLM invented: unknown catalog ids, ports, or columns.

    A hallucinated column does not raise — it quietly renders an empty widget —
    so the mapping is removed and the deterministic column inference takes over.
    """
    by_node_port = {(p.get("node_id"), p.get("port")): p for p in ports}
    by_port = {p.get("port"): p for p in ports}
    grounded: list[dict[str, Any]] = []
    for spec in specs:
        if spec.get("catalog_id") not in allowed_ids:
            continue
        port = spec.get("source_port")
        summary = by_node_port.get((spec.get("source_node"), port)) or by_port.get(port)
        if port and summary is None:
            continue
        if summary:
            columns = {str(col) for col in summary.get("columns") or []}
            field_map = spec.get("field_map") or {}
            kept = {
                key: value
                for key, value in field_map.items()
                if not isinstance(value, str) or value == "_row_count" or value in columns
            }
            if kept != field_map:
                spec = {**spec, "field_map": kept}
            if not spec.get("source_node") and summary.get("node_id"):
                spec = {**spec, "source_node": summary["node_id"]}
        grounded.append(spec)
    return grounded


def _find_env(run: Run, node_id: str | None, port: str | None):
    for step in reversed(run.steps):
        if node_id and step.node_id != node_id:
            continue
        for env in step.outputs:
            if port and env.port != port:
                continue
            return step, env
    if run.steps:
        step = run.steps[-1]
        if step.outputs:
            return step, step.outputs[-1]
    return None, None


def _counts(rows: list[dict[str, Any]], field: str, limit: int = 8) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for row in rows:
        key = row.get(field)
        if key is None or key == "":
            key = "(empty)"
        counter[str(key)] += 1
    return [{"name": name, "value": count} for name, count in counter.most_common(limit)]


def _series(rows: list[dict[str, Any]], field: str, limit: int = 40) -> list[dict[str, Any]]:
    points = []
    for index, row in enumerate(rows[:limit]):
        value = row.get(field)
        if not _is_number(value):
            continue
        points.append({"name": str(index + 1), "value": _to_number(value)})
    return points


def _explain_block(step, env, column: str | None, aggregation: str, why: str | None = None) -> dict[str, Any]:
    return {
        "source_node": step.node_id if step else None,
        "source_port": env.port if env else None,
        "column": column,
        "aggregation": aggregation,
        "why": why or (f"{aggregation} of {column}" if column else aggregation),
    }


_CATALOG_LABELS = {
    "kpi_card": "Summary",
    "bar_chart": "Breakdown",
    "pie_chart": "Mix",
    "donut_chart": "Share",
    "line_chart": "Trend",
    "area_chart": "Trend",
    "grouped_bar_chart": "Actual vs expected",
    "stacked_bar_chart": "Composition",
    "variance_chart": "Variance",
    "insight_table": "Rows",
    "breakdown_table": "Breakdown",
    "exception_table": "Exceptions",
    "rate_gauge": "Rate",
    "narrative_card": "Readout",
    "action_list": "Actions",
    "mail_reply_table": "Draft replies",
}


def _fallback_title(catalog_id: str, field_map: dict[str, Any], env) -> str:
    """A widget without a title still needs a readable, distinct one."""
    base = _CATALOG_LABELS.get(catalog_id, catalog_id.replace("_", " ").title())
    hint = field_map.get("category") or field_map.get("value") or field_map.get("actual")
    if hint and hint != "_row_count":
        return f"{str(hint).replace('_', ' ').strip().title()} · {base}"
    port = getattr(env, "port", None)
    return f"{base} · {port}" if port else base


def fill_widget(run: Run, spec: dict[str, Any], pipeline: Pipeline | None = None) -> dict[str, Any] | None:
    catalog_id = spec.get("catalog_id")
    if catalog_id not in CATALOG_IDS:
        return None
    step, env = _find_env(run, spec.get("source_node"), spec.get("source_port"))
    rows = _rows(env.payload or {}) if env else []
    field_map = spec.get("field_map") or {}
    limit = int(spec.get("limit") or 12)
    title = spec.get("title") or _fallback_title(catalog_id, field_map, env)
    filled: dict[str, Any] = {
        "catalog_id": catalog_id,
        "title": title,
        "source_node": step.node_id if step else None,
        "source_port": env.port if env else None,
    }
    if catalog_id == "kpi_card":
        field = field_map.get("value")
        if spec.get("value") is not None and not field:
            filled["value"] = spec["value"]
            filled["subtitle"] = spec.get("subtitle") or ""
            filled["explain"] = _explain_block(step, env, None, "count")
            return filled
        if field == "_row_count" or not field:
            filled["value"] = len(rows)
            filled["subtitle"] = spec.get("subtitle") or (f"{env.port} rows" if env else "rows")
            filled["explain"] = _explain_block(step, env, None, "count")
        elif rows:
            stats = column_stats(rows, field)
            filled["value"] = stats.get("total")
            filled["unit"] = spec.get("unit")
            filled["subtitle"] = spec.get("subtitle") or field
            filled["trend"] = sparkline(rows, field)
            if stats.get("mean") is not None and stats.get("total") is not None:
                filled["delta"] = round(stats["total"] - stats["mean"] * max(stats["count"] - 1, 1), 2) if stats["count"] else None
            filled["explain"] = _explain_block(step, env, field, "sum")
        else:
            filled["value"] = 0
        return filled
    if catalog_id in {"bar_chart", "pie_chart", "donut_chart"}:
        field = field_map.get("category")
        value = field_map.get("value")
        if not field and rows:
            field = next((key for key in rows[0] if not _is_number(rows[0].get(key))), None)
        filled["data"] = group_sum(rows, field, value, limit) if field else []
        filled["explain"] = _explain_block(step, env, field, "group")
        return filled
    if catalog_id == "stacked_bar_chart":
        category = field_map.get("category")
        stack = field_map.get("stack") or field_map.get("status") or "status"
        if not category and rows:
            category = next((key for key in rows[0] if not _is_number(rows[0].get(key))), None)
        groups: dict[str, dict[str, float]] = {}
        series: set[str] = set()
        for row in rows:
            cat = str(row.get(category) or "(empty)") if category else "(all)"
            st = str(row.get(stack) or row.get("verdict") or (env.port if env else "row"))
            groups.setdefault(cat, {})
            groups[cat][st] = groups[cat].get(st, 0) + 1
            series.add(st)
        filled["data"] = [{"name": name, **values} for name, values in list(groups.items())[:limit]]
        filled["series"] = sorted(series)
        filled["explain"] = _explain_block(step, env, category, "stack")
        return filled
    if catalog_id in {"grouped_bar_chart", "variance_chart"}:
        actual = field_map.get("actual") or field_map.get("value")
        expected = field_map.get("expected")
        label = field_map.get("label") or field_map.get("category")
        if not actual and rows:
            nums = [k for k in rows[0] if _is_number(rows[0].get(k))]
            actual = nums[0] if nums else None
            expected = nums[1] if len(nums) > 1 else None
        data = variance(rows, actual, expected, label, limit) if actual and expected else []
        filled["data"] = data
        filled["explain"] = _explain_block(step, env, actual, "variance")
        return filled
    if catalog_id in {"line_chart", "area_chart"}:
        field = field_map.get("value")
        date_field = field_map.get("date")
        if not field and rows:
            field = next((key for key in rows[0] if _is_number(rows[0].get(key))), None)
        dates = date_columns(rows, list(rows[0].keys()) if rows else [])
        if not date_field and dates:
            date_field = dates[0]
        if date_field and field:
            filled["data"] = timeseries(rows, date_field, field, max(limit, 20))
        else:
            filled["data"] = _series(rows, field, max(limit, 20)) if field else []
        filled["explain"] = _explain_block(step, env, field, "series")
        return filled
    if catalog_id == "insight_table":
        columns = list(rows[0].keys())[:8] if rows else []
        filled["columns"] = columns
        filled["rows"] = [{col: row.get(col) for col in columns} for row in rows[: min(limit, 20)]]
        filled["explain"] = _explain_block(step, env, None, "table")
        return filled
    if catalog_id == "breakdown_table":
        category = field_map.get("category")
        value = field_map.get("value")
        if not category and rows:
            category = next((key for key in rows[0] if not _is_number(rows[0].get(key))), None)
        data = group_sum(rows, category, value, limit) if category else []
        filled["columns"] = [category or "group", value or "count"]
        filled["rows"] = [{filled["columns"][0]: item["name"], filled["columns"][1]: item["value"]} for item in data]
        total = sum(item["value"] for item in data)
        if filled["rows"]:
            filled["rows"].append({filled["columns"][0]: "Total", filled["columns"][1]: round(total, 2)})
        filled["explain"] = _explain_block(step, env, category, "breakdown")
        return filled
    if catalog_id == "exception_table":
        columns = list(rows[0].keys())[:8] if rows else []
        filled["columns"] = columns
        filled["rows"] = [{col: row.get(col) for col in columns} for row in rows[: min(limit, 20)]]
        filled["explain"] = _explain_block(step, env, None, "exceptions")
        return filled
    if catalog_id == "rate_gauge":
        other = spec.get("compare_port")
        other_rows = []
        if other:
            _, other_env = _find_env(run, spec.get("source_node"), other)
            other_rows = _rows(other_env.payload or {}) if other_env else []
        else:
            ports = port_summaries(run)
            match_n = next((p for p in ports if p["port"] in {"matched", "approved"}), None)
            rest_n = sum(p["row_count"] for p in ports if p["port"] in {"exceptions", "flagged", "escalated", "residuals"})
            a = match_n["row_count"] if match_n else len(rows)
            filled["value"] = round((a / (a + rest_n) * 100), 1) if (a + rest_n) else 0
            filled["subtitle"] = spec.get("subtitle") or "clearance rate"
            filled["unit"] = "%"
            filled["explain"] = _explain_block(step, env, None, "rate")
            return filled
        body = rate(rows, other_rows)
        filled["value"] = body["value"]
        filled["unit"] = "%"
        filled["subtitle"] = spec.get("subtitle") or "rate"
        filled["explain"] = _explain_block(step, env, None, "rate")
        return filled
    if catalog_id == "narrative_card":
        filled["text"] = spec.get("text") or ""
        filled["explain"] = _explain_block(step, env, None, "narrative")
        return filled
    if catalog_id == "action_list":
        actions = []
        if env and env.port in {"exceptions", "flagged", "escalated", "residuals"}:
            actions.append(f"Review {len(rows)} {env.port} row(s) from {step.agent if step else 'pipeline'}.")
        if step and step.skip_reason:
            actions.append(f"{step.agent} skipped: {step.skip_reason}")
        if not actions:
            actions.append("Download Excel/PDF from Reports and confirm exceptions with the owner.")
        filled["actions"] = actions[:6]
        filled["explain"] = _explain_block(step, env, None, "actions")
        return filled
    if catalog_id == "mail_reply_table":
        from app.services.mail import collect_mail_rows

        mail_rows = collect_mail_rows(run)
        filled["columns"] = [
            "subject",
            "from",
            "qty",
            "item",
            "location",
            "verdict",
            "send_status",
            "draft_subject",
        ]
        filled["rows"] = mail_rows
        filled["mail_rows"] = mail_rows
        filled["explain"] = _explain_block(step, env, None, "mail")
        return filled
    return filled


def heuristic_specs(run: Run) -> list[dict[str, Any]]:
    from app.services.mail import collect_mail_rows, mail_kpis

    mail_rows = collect_mail_rows(run)
    if mail_rows:
        kpis = mail_kpis(run)
        specs: list[dict[str, Any]] = [
            {"catalog_id": "kpi_card", "title": "Unread fetched", "field_map": {}, "value": kpis["unread_fetched"], "subtitle": "IMAP UNSEEN"},
            {"catalog_id": "kpi_card", "title": "PR kept", "field_map": {}, "value": kpis["kept"], "subtitle": "subject gate"},
            {"catalog_id": "kpi_card", "title": "Skipped noise", "field_map": {}, "value": kpis["skipped_noise"], "subtitle": "not PR/PO"},
            {"catalog_id": "kpi_card", "title": "Waiting send", "field_map": {}, "value": kpis["waiting"], "subtitle": "drafts"},
            {"catalog_id": "mail_reply_table", "title": "Draft replies"},
            {"catalog_id": "narrative_card", "title": "Readout"},
        ]
        return specs
    ports = port_summaries(run)
    specs: list[dict[str, Any]] = []
    for port in ports:
        specs.append(
            {
                "catalog_id": "kpi_card",
                "title": f"{port['agent']} · {port['port']}",
                "source_node": port["node_id"],
                "source_port": port["port"],
                "field_map": {"value": "_row_count"},
            }
        )
    cat_port = next((p for p in reversed(ports) if p["categorical"] and p["row_count"]), None)
    if cat_port:
        specs.append(
            {
                "catalog_id": "bar_chart",
                "title": f"{cat_port['categorical'][0]} mix",
                "source_node": cat_port["node_id"],
                "source_port": cat_port["port"],
                "field_map": {"category": cat_port["categorical"][0]},
            }
        )
        specs.append(
            {
                "catalog_id": "donut_chart",
                "title": f"{cat_port['categorical'][0]} share",
                "source_node": cat_port["node_id"],
                "source_port": cat_port["port"],
                "field_map": {"category": cat_port["categorical"][0]},
            }
        )
        specs.append(
            {
                "catalog_id": "pie_chart",
                "title": f"{cat_port['categorical'][0]} mix (pie)",
                "source_node": cat_port["node_id"],
                "source_port": cat_port["port"],
                "field_map": {"category": cat_port["categorical"][0]},
            }
        )
    num_port = next((p for p in reversed(ports) if p["numeric"] and p["row_count"]), None)
    if num_port:
        specs.append(
            {
                "catalog_id": "line_chart",
                "title": num_port["numeric"][0],
                "source_node": num_port["node_id"],
                "source_port": num_port["port"],
                "field_map": {"value": num_port["numeric"][0]},
            }
        )
    last = ports[-1] if ports else None
    if last:
        specs.append(
            {
                "catalog_id": "insight_table",
                "title": "Result rows",
                "source_node": last["node_id"],
                "source_port": last["port"],
                "limit": 12,
            }
        )
    exception = next((p for p in ports if p["port"] in {"exceptions", "flagged", "escalated", "residuals"}), None)
    if exception:
        specs.append(
            {
                "catalog_id": "exception_table",
                "title": f"{exception['port']} rows",
                "source_node": exception["node_id"],
                "source_port": exception["port"],
                "limit": 12,
            }
        )
    if cat_port:
        specs.append(
            {
                "catalog_id": "breakdown_table",
                "title": f"{cat_port['categorical'][0]} breakdown",
                "source_node": cat_port["node_id"],
                "source_port": cat_port["port"],
                "field_map": {"category": cat_port["categorical"][0]},
            }
        )
    if any(p["port"] in {"matched", "approved"} for p in ports):
        match_p = next(p for p in ports if p["port"] in {"matched", "approved"})
        specs.append(
            {
                "catalog_id": "rate_gauge",
                "title": "Clearance rate",
                "source_node": match_p["node_id"],
                "source_port": match_p["port"],
            }
        )
    nums = [p for p in ports if len(p.get("numeric") or []) >= 2]
    if nums:
        nport = nums[-1]
        specs.append(
            {
                "catalog_id": "variance_chart",
                "title": f"{nport['numeric'][0]} vs {nport['numeric'][1]}",
                "source_node": nport["node_id"],
                "source_port": nport["port"],
                "field_map": {"actual": nport["numeric"][0], "expected": nport["numeric"][1]},
            }
        )
    dated = next((p for p in reversed(ports) if p.get("date_columns") and p.get("numeric")), None)
    if dated:
        specs.append(
            {
                "catalog_id": "area_chart",
                "title": dated["numeric"][0],
                "source_node": dated["node_id"],
                "source_port": dated["port"],
                "field_map": {"date": dated["date_columns"][0], "value": dated["numeric"][0]},
            }
        )
    specs.append({"catalog_id": "narrative_card", "title": "Readout"})
    specs.append(
        {
            "catalog_id": "action_list",
            "title": "Actions",
            "source_node": (exception or last or {}).get("node_id") if (exception or last) else None,
            "source_port": (exception or last or {}).get("port") if (exception or last) else None,
        }
    )
    return specs[:12]


async def compile_dashboard(run: Run, llm: LLMProvider | None = None, pipeline: Pipeline | None = None) -> dict[str, Any]:
    from app.services.mail import collect_mail_rows

    ports = port_summaries(run)
    specs = heuristic_specs(run)
    source = "heuristic"
    profile = use_case_profile(pipeline, run) if pipeline else {"name": run.pipeline_id, "purpose": "", "brief": "", "ports": ports, "status": run.status, "totals": sum(p["row_count"] for p in ports)}
    if collect_mail_rows(run):
        llm = None
    if llm and ports:
        prompt = (
            "Pick dashboard widgets from the catalog. JSON only matching the schema. "
            "Use only catalog_id values listed. Prefer 8-12 widgets: KPIs, mix chart, "
            "variance or area, table, narrative, actions.\n"
            "Grounding rules for this task:\n"
            "- source_node and source_port must be copied from the Ports list below.\n"
            "- Every field_map value must be copied character for character from the "
            "'columns' array of that same port, or be the literal '_row_count'.\n"
            "- If no real column fits a field_map slot, omit the slot entirely.\n"
            "- Give every widget a short title taken from the use case or the column name; "
            "two widgets must not share a title.\n\n"
            f"Use case: {json.dumps({k: profile.get(k) for k in ('name', 'purpose', 'brief', 'status', 'totals')}, default=str)[:2500]}\n"
            f"Catalog:\n{catalog_digest()}\n\nPorts:\n{json.dumps(ports, default=str)[:6000]}\n"
        )
        try:
            body = await llm.complete_json("reasoning", prompt, SELECT_SCHEMA, 0.1)
            picked = ground_specs(body.get("widgets") or [], ports, CATALOG_IDS)
            if picked:
                specs = picked
                source = "catalog"
        except (LLMError, Exception):
            source = "heuristic"
    widgets = []
    facts = [
        f"{p['agent']} {p['port']}: {p['row_count']} rows"
        for p in ports
        if p["row_count"]
    ][:8]
    narrative = await narrate(profile, facts, llm)
    for spec in specs:
        if spec.get("catalog_id") == "narrative_card" and not spec.get("text"):
            spec = {**spec, "text": narrative}
        filled = fill_widget(run, spec, pipeline)
        if filled:
            widgets.append(filled)
    return {"source": source, "widgets": widgets, "ports": ports, "profile": profile}


def lineage_model(pipeline: Pipeline, run: Run) -> dict[str, Any]:
    inputs = []
    for node in pipeline.nodes:
        if node.agent == "ingestion":
            inputs.append(
                {
                    "node_id": node.id,
                    "label": node.label,
                    "filename": (node.config or {}).get("filename"),
                    "mode": node.mode,
                }
            )
    steps = []
    by_id = {step.node_id: step for step in run.steps}
    for node in pipeline.nodes:
        step = by_id.get(node.id)
        cfg = node.config or {}
        steps.append(
            {
                "node_id": node.id,
                "agent": node.agent,
                "label": node.label,
                "status": step.status if step else "pending",
                "summary": step.summary if step else "",
                "skip_reason": step.skip_reason if step else None,
                "catalog_id": cfg.get("catalog_id"),
                "formula_en": cfg.get("formula_en"),
                "ast": cfg.get("ast"),
                "keys": cfg.get("keys"),
                "policy": cfg.get("policy"),
                "formats": cfg.get("formats"),
                "output_ports": [env.port for env in step.outputs] if step else [],
                "row_counts": {
                    env.port: len(_rows(env.payload or {})) for env in (step.outputs if step else [])
                },
            }
        )
    outputs = []
    for name in run.artifacts:
        outputs.append({"artifact": Path(name).name, "path": name})
    from app.services.explain import column_lineage, derivation_cards, sheet_cards

    return {
        "inputs": inputs,
        "steps": steps,
        "outputs": outputs,
        "status": run.status,
        "cards": derivation_cards(pipeline, run),
        "sheets": sheet_cards(pipeline, run),
        "columns": column_lineage(pipeline, run),
        "profile": use_case_profile(pipeline, run),
    }
