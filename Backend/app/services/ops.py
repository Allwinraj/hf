from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agents.base import AgentRegistry
from app.core.llm import LLMError, LLMProvider
from app.core.storage import Storage
from app.engine.persist import load_run, save_run
from app.engine.runner import PipelineRunner
from app.models.pipeline import Pipeline
from app.models.run import Run
from app.services.knowledge import load_knowledge
from app.services.library import file_slots, slot_path


def bind_library_paths(storage: Storage, pipeline: Pipeline) -> Pipeline:
    nodes = []
    for node in pipeline.nodes:
        cfg = dict(node.config or {})
        if node.agent == "ingestion":
            filename = str(cfg.get("filename") or Path(str(cfg.get("path") or "")).name)
            if filename:
                dest = slot_path(storage, pipeline, filename)
                if dest.exists():
                    cfg["path"] = str(dest)
                    cfg["filename"] = filename
        nodes.append(node.model_copy(update={"config": cfg}))
    return pipeline.model_copy(update={"nodes": nodes})


def missing_files(storage: Storage, pipeline: Pipeline) -> list[str]:
    missing = []
    for slot in file_slots(pipeline):
        path = slot_path(storage, pipeline, slot["filename"])
        if not path.exists():
            missing.append(slot["filename"])
    return missing


async def run_library_pipeline(
    storage: Storage,
    llm: LLMProvider,
    registry: AgentRegistry,
    pipeline: Pipeline,
    on_event=None,
) -> Run:
    missing = missing_files(storage, pipeline)
    if missing:
        raise ValueError("upload these files first (same names): " + ", ".join(missing))
    pipeline = bind_library_paths(storage, pipeline)
    knowledge = None
    if storage.exists("knowledge", f"{pipeline.id}.json"):
        knowledge = load_knowledge(storage, pipeline.id)
    runner = PipelineRunner(registry, storage, llm, on_event=on_event)
    run = await runner.run(pipeline, knowledge=knowledge)
    run.extra["pipeline_id"] = pipeline.id
    run.extra["source"] = "library"
    save_run(storage, run)
    return run


def _compact_run(run) -> dict[str, Any]:
    steps = []
    for step in run.steps:
        sample_rows = []
        formulas = []
        for env in step.outputs:
            payload = env.payload or {}
            if payload.get("formula_en") or payload.get("ast"):
                formulas.append(
                    {
                        "formula_en": payload.get("formula_en"),
                        "ast": payload.get("ast"),
                        "catalog_id": payload.get("catalog_id"),
                    }
                )
            rows = payload.get("rows")
            if isinstance(rows, list):
                sample_rows.append(rows[:8])
        steps.append(
            {
                "node_id": step.node_id,
                "agent": step.agent,
                "status": step.status,
                "error": step.error,
                "ports": [env.port for env in step.outputs],
                "formulas": formulas,
                "sample_rows": sample_rows[:2],
            }
        )
    return {
        "id": run.id,
        "status": run.status,
        "error": run.error,
        "artifacts": run.artifacts,
        "steps": steps,
    }


async def answer_run_question(
    llm: LLMProvider,
    pipeline: Pipeline,
    run_id: str,
    storage: Storage,
    question: str,
    view: str | None = None,
    node_id: str | None = None,
    port: str | None = None,
    row_index: int | None = None,
) -> str:
    run = load_run(storage, run_id)
    view_name = {
        "how": "how_it_works",
        "how_it_works": "how_it_works",
        "reports": "reports",
        "dashboard": "dashboard",
        "lineage": "lineage",
    }.get((view or "").strip(), view or "run")
    meta = pipeline.meta or {}
    extra = ""
    if view_name == "dashboard":
        try:
            from app.services.dashboard import compile_dashboard

            dash = await compile_dashboard(run, None, pipeline)
            extra += "Dashboard widgets: " + str(
                [
                    {
                        "title": w.get("title"),
                        "catalog_id": w.get("catalog_id"),
                        "value": w.get("value"),
                    }
                    for w in dash.get("widgets") or []
                ]
            )[:4000]
        except Exception:
            extra += ""
    if view_name == "how_it_works":
        try:
            from app.services.explain import column_lineage, sheet_cards

            extra += "Sheets: " + str(sheet_cards(pipeline, run))[:2500]
            extra += "\nColumns: " + str(
                [
                    {"column": c.get("column"), "origin": c.get("origin"), "why": c.get("why")}
                    for c in column_lineage(pipeline, run)[:24]
                ]
            )[:2500]
        except Exception:
            extra += ""
    if node_id and port is not None and row_index is not None:
        from app.services.explain import row_trace

        extra += "\nRow trace: " + str(row_trace(pipeline, run, node_id, port, row_index))[:4000]
    nodes = [
        {
            "id": n.id,
            "agent": n.agent,
            "label": n.label,
            "config": {
                k: n.config.get(k)
                for k in (
                    "filename",
                    "keys",
                    "window_days",
                    "formula_en",
                    "catalog_id",
                    "ast",
                    "gate_ast",
                    "policy",
                    "formats",
                    "input_map",
                    "output_column",
                )
                if k in (n.config or {})
            },
        }
        for n in pipeline.nodes
    ]
    prompt = (
        "You explain a finance pipeline run to the person who designed it. "
        "Use only the node config, use-case brief, and run trace. Be concrete about how numbers "
        "were calculated (formula_en / ast / keys / window). If the current view "
        "is dashboard, lineage, or how_it_works, answer in that context. "
        "If the trace does not contain the answer, say so. "
        "Reply in GitHub-flavored Markdown: short headings, bullets, and tables when listing rows or amounts.\n\n"
        f"Current view: {view_name}\n"
        f"Pipeline: {pipeline.name} {pipeline.version}\n"
        f"Purpose: {meta.get('purpose') or ''}\n"
        f"Brief: {str(meta.get('brief') or '')[:2000]}\n"
        f"Nodes: {nodes}\n"
        f"Run: {_compact_run(run)}\n"
        f"{extra}\n"
        f"Question: {question}\n"
    )
    try:
        return (await llm.complete("reasoning", prompt, 0.2)).strip()
    except LLMError:
        try:
            return (await llm.complete("general", prompt, 0.2)).strip()
        except LLMError:
            return (
                "I could not reach the model. From the last run: "
                f"status {run.status}. Artifacts: {', '.join(run.artifacts) or 'none'}."
            )


def library_card(pipeline: Pipeline) -> dict[str, Any]:
    return {
        "id": pipeline.id,
        "name": pipeline.name,
        "version": pipeline.version,
        "nodes": len(pipeline.nodes),
        "brief": (pipeline.meta or {}).get("brief"),
        "file_slots": file_slots(pipeline),
    }
