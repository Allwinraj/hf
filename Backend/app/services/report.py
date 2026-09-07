from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

import yaml

from app.core.llm import LLMError, LLMProvider
from app.core.settings import BACKEND_ROOT
from app.core.storage import Storage
from app.models.envelope import Envelope
from app.models.pipeline import Pipeline
from app.models.run import Run
from app.services.dashboard import fill_widget, ground_specs, heuristic_specs, port_summaries
from app.services.explain import column_lineage, derivation_cards, row_trace, sheet_cards, sheet_rows
from app.services.exporter import (
    Stream,
    collect_streams,
    flatten_row,
    resolve_theme,
    write_pdf_spec,
    write_workbook_spec,
)
from app.services.insight import rows_of, use_case_profile

SECTION_IDS = {
    "cover",
    "executive_summary",
    "kpi_grid",
    "chart_block",
    "data_sheet",
    "exception_sheet",
    "breakdown_sheet",
    "sheet_notes",
    "column_guide",
    "row_justification",
    "derivation_appendix",
    "signoff",
}

SELECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["sections"],
    "properties": {
        "sections": {
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
                },
            },
        }
    },
}


@lru_cache
def report_catalog_digest() -> str:
    path = BACKEND_ROOT / "data" / "reports" / "v1.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    lines = []
    for item in data.get("sections") or []:
        lines.append(f"{item.get('id')}: {item.get('description')}")
    return "\n".join(lines)


def heuristic_report_spec(pipeline: Pipeline, run: Run) -> list[dict[str, Any]]:
    ports = port_summaries(run)
    sheets = sheet_cards(pipeline, run)
    sections: list[dict[str, Any]] = [
        {"catalog_id": "cover", "title": pipeline.name or "Nexus Report"},
        {"catalog_id": "executive_summary", "title": "Executive summary"},
        {"catalog_id": "kpi_grid", "title": "KPIs"},
        {"catalog_id": "sheet_notes", "title": "Sheet notes"},
        {"catalog_id": "column_guide", "title": "Column guide"},
    ]
    for sheet in sheets:
        if sheet["row_count"] == 0:
            continue
        kind = "exception_sheet" if sheet["port"] in {"exceptions", "flagged", "escalated", "residuals"} else "data_sheet"
        sections.append(
            {
                "catalog_id": kind,
                "title": sheet["sheet_name"],
                "source_node": sheet["node_id"],
                "source_port": sheet["port"],
            }
        )
    if any(p["port"] in {"exceptions", "flagged", "escalated"} for p in ports):
        sections.append({"catalog_id": "row_justification", "title": "Why"})
    sections.append({"catalog_id": "derivation_appendix", "title": "Derivation"})
    sections.append({"catalog_id": "signoff", "title": "Sign-off"})
    return sections


async def compile_report_spec(
    pipeline: Pipeline,
    run: Run,
    fmt: str = "xlsx",
    llm: LLMProvider | None = None,
) -> dict[str, Any]:
    sections = heuristic_report_spec(pipeline, run)
    source = "heuristic"
    profile = use_case_profile(pipeline, run)
    ports = port_summaries(run)
    if llm and ports:
        prompt = (
            "Pick report sections from the catalog. JSON only. Use only catalog_id values listed.\n"
            "Grounding rules for this task:\n"
            "- source_node and source_port must be copied from the Ports list below.\n"
            "- Any column you name must be copied character for character from the "
            "'columns' array of that same port.\n"
            "- If no real column fits, omit it rather than inventing one.\n\n"
            f"Format: {fmt}\nUse case: {profile.get('purpose') or profile.get('brief') or profile.get('name')}\n"
            f"Catalog:\n{report_catalog_digest()}\n\nPorts:\n{json.dumps(ports, default=str)[:5000]}\n"
        )
        try:
            body = await llm.complete_json("reasoning", prompt, SELECT_SCHEMA, 0.1)
            picked = ground_specs(body.get("sections") or [], ports, SECTION_IDS)
            if picked:
                sections = picked
                source = "catalog"
        except (LLMError, Exception):
            source = "heuristic"
    return {
        "source": source,
        "format": fmt,
        "title": pipeline.name or "Nexus Report",
        "sections": sections,
        "profile": profile,
        "sheets": sheet_cards(pipeline, run),
    }


def _streams_for_sections(pipeline: Pipeline, run: Run, sections: list[dict[str, Any]]) -> list[Stream]:
    streams: list[Stream] = []
    used: set[str] = set()
    justify = any(item.get("catalog_id") == "row_justification" for item in sections)
    for item in sections:
        kind = item.get("catalog_id")
        if kind not in {"data_sheet", "exception_sheet"}:
            continue
        node_id = item.get("source_node")
        port = item.get("source_port")
        page = sheet_rows(run, str(node_id), str(port), offset=0, limit=5000)
        rows = list(page["rows"])
        if justify and kind == "exception_sheet":
            for row in rows:
                idx = int(row.get("_row_index") or 0)
                try:
                    trace = row_trace(pipeline, run, str(node_id), str(port), idx)
                    why = next(
                        (
                            step.get("explanation") or step.get("why") or step.get("substituted")
                            for step in reversed(trace.get("steps") or [])
                            if step.get("explanation") or step.get("why") or step.get("substituted")
                        ),
                        "",
                    )
                except Exception:
                    why = ""
                row["why"] = why
        name = str(item.get("title") or port or "Data")
        streams.append(Stream(name=name[:31], port=str(port or "default"), kind=kind, rows=rows))
        used.add(name.lower())
    if not streams:
        envs = []
        for step in run.steps:
            envs.extend(step.outputs)
        dummy = Envelope(run_id=run.id, node_id="out", port="default", payload={"rows": []}, emitted_by="report")
        streams = collect_streams(envs or [dummy], {})
    return streams


def render_report(spec: dict[str, Any], pipeline: Pipeline, run: Run, fmt: str = "xlsx") -> bytes:
    sections = list(spec.get("sections") or heuristic_report_spec(pipeline, run))
    streams = _streams_for_sections(pipeline, run, sections)
    theme = resolve_theme("executive_classic")
    title = str(spec.get("title") or pipeline.name or "Nexus Report")
    notes = [s["purpose"] for s in sheet_cards(pipeline, run)]
    guide = column_lineage(pipeline, run)
    appendix = []
    for card in derivation_cards(pipeline, run):
        appendix.append(f"{card['label']} · {card['agent']}: {card.get('why') or ''}")
    if fmt == "pdf":
        return write_pdf_spec(streams, theme=theme, title=title, notes=notes)
    return write_workbook_spec(
        streams,
        theme=theme,
        title=title,
        sections=sections,
        notes=notes,
        column_guide=guide,
        appendix=appendix,
    )


def safe_filename(name: str, fmt: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "report"
    stem = stem[:60]
    ext = "pdf" if fmt == "pdf" else "xlsx"
    if stem.lower().endswith(f".{ext}"):
        return stem
    return f"{stem}.{ext}"


def write_generated_report(
    storage: Storage,
    run: Run,
    data: bytes,
    filename: str,
) -> str:
    rel = f"runs/{run.id}/artifacts/{filename}"
    storage.write_bytes(data, *rel.split("/"))
    if filename not in run.artifacts and rel not in run.artifacts:
        run.artifacts.append(filename)
    return rel
