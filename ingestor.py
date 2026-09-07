from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from app.core.llm import LLMError
from app.agents.base import RunContext, registry
from app.models.envelope import Envelope
from app.models.knowledge import KnowledgeDocument, SessionKnowledge
from app.services.knowledge import (
    SCHEMA_JSON_SCHEMA,
    chunk_text,
    extract_facts,
    save_knowledge,
    upsert_document,
)
from app.services.parser import (
    ParseError,
    apply_overrides,
    columns_as_dicts,
    parse_file,
)

IngestMode = Literal["data", "knowledge", "mailbox"]


class Ingestor:
    """One agent, two modes. Mode comes from upload intent, not file extension."""

    name = "ingestion"

    async def execute(self, ctx: RunContext, env: Envelope) -> list[Envelope]:
        config = dict(ctx.node.config) if ctx.node else dict(env.payload)
        mode = config.get("mode") or env.payload.get("mode") or "data"
        if mode not in {"data", "knowledge", "mailbox"}:
            raise ValueError(f"ingestion mode must be data, knowledge, or mailbox, got {mode!r}")
        if mode == "mailbox":
            return await self._mailbox(ctx, env, config)
        path = _resolve_path(ctx, config)
        parsed = parse_file(
            path,
            sheet=config.get("sheet"),
            header_row=config.get("header_row"),
        )
        file_id = str(config.get("file_id") or path.stem)
        if mode == "data":
            return await self._data(ctx, env, config, parsed, file_id, path)
        return await self._knowledge(ctx, env, config, parsed, file_id, path)

    async def _mailbox(self, ctx, env, config: dict[str, Any]) -> list[Envelope]:
        from app.services.mail import extract_pr, fetch_unseen, mark_seen
        from app.services.mailbox_defaults import mailbox_config

        cfg = mailbox_config(config)
        messages = fetch_unseen(cfg)
        skipped: list[dict[str, Any]] = []
        kept_rows: list[dict[str, Any]] = []
        for msg in messages:
            if not msg.kept:
                skipped.append(
                    {"mail_id": msg.uid, "subject": msg.subject, "from": msg.from_addr, "skip_reason": msg.skip_reason}
                )
                continue
            kept_rows.append(extract_pr(msg))
        mark_seen(cfg, [m.uid for m in messages if m.uid])
        send_details = str(cfg.get("send_details") or config.get("send_details") or "")
        for row in kept_rows:
            row["send_details"] = send_details
            row["send_status"] = "draft"
        rows = kept_rows
        node_id = ctx.node.id if ctx.node else env.node_id
        payload: dict[str, Any] = {
            "kind": "mail_prs",
            "unread_fetched": len(messages),
            "kept": len(rows),
            "skipped_noise": len(skipped),
            "skipped": skipped,
            "schema": [
                {"name": key, "type": "string", "samples": [], "source_name": key}
                for key in (
                    "mail_id",
                    "subject",
                    "from",
                    "qty",
                    "item",
                    "location",
                    "needed_by",
                    "cost_centre",
                    "budget",
                    "spec_ref",
                    "send_status",
                )
            ],
            "rows": rows,
        }
        return [
            Envelope(
                run_id=ctx.run_id,
                node_id=node_id,
                port="default",
                payload=payload,
                schema_ref="mailbox",
                emitted_by="ingestion@v1",
            )
        ]

    async def _data(self, ctx, env, config, parsed, file_id, path: Path) -> list[Envelope]:
        if not parsed.tables:
            raise ParseError("data mode requires a tabular structure")
        table = parsed.tables[0]
        columns, rows = apply_overrides(
            table.columns, table.rows, config.get("schema_overrides")
        )
        if config.get("use_llm_schema", False):
            columns, rows = await self._refine_schema(ctx, columns, rows)
        schema = columns_as_dicts(columns)
        payload: dict[str, Any] = {
            "kind": "data",
            "file_id": file_id,
            "path": str(path),
            "sheet": table.sheet,
            "header_row": table.header_row,
            "schema": schema,
            "rows": rows,
        }
        return [
            Envelope(
                run_id=ctx.run_id,
                node_id=ctx.node.id if ctx.node else env.node_id,
                port="default",
                payload=payload,
                schema_ref=file_id,
                emitted_by="ingestion@v1",
            )
        ]

    async def _knowledge(self, ctx, env, config, parsed, file_id, path: Path) -> list[Envelope]:
        chunks = chunk_text(parsed.text, file_id=file_id)
        facts = await extract_facts(ctx.llm, chunks)
        document = KnowledgeDocument(
            file_id=file_id,
            original_path=str(path),
            chunks=chunks,
            facts=facts,
        )
        session_id = str(config.get("session_id") or ctx.run_id)
        store = ctx.knowledge_store or SessionKnowledge(session_id=session_id)
        upsert_document(store, document)
        ctx.knowledge_store = store
        save_knowledge(ctx.storage, store)
        fact_payload = [f.model_dump(mode="json") for f in facts]
        knowledge_context = {
            "file_id": file_id,
            "original_path": str(path),
            "facts": fact_payload,
            "chunk_ids": [c.id for c in chunks],
        }
        return [
            Envelope(
                run_id=ctx.run_id,
                node_id=ctx.node.id if ctx.node else env.node_id,
                port="default",
                payload={"kind": "knowledge", **knowledge_context},
                knowledge_context=knowledge_context,
                emitted_by="ingestion@v1",
            )
        ]

    async def _refine_schema(self, ctx: RunContext, columns, rows):
        preview = {
            "columns": [{"name": c.name, "type": c.type, "samples": c.samples} for c in columns],
            "sample_rows": rows[:8],
        }
        prompt = (
            "Infer cleaner column names and types for this finance table. "
            "type must be string, integer, decimal, date, or boolean. "
            "Keep the same column count and order. Do not invent columns.\n"
            f"{preview}"
        )
        try:
            result = await ctx.llm.complete_json("extraction", prompt, SCHEMA_JSON_SCHEMA)
        except LLMError:
            return columns, rows
        refined = result.get("columns") or []
        if len(refined) != len(columns):
            return columns, rows
        rename = {}
        new_cols = []
        for old, spec in zip(columns, refined, strict=True):
            new_name = spec.get("name") or old.name
            new_type = spec.get("type") or old.type
            if new_type not in {"string", "integer", "decimal", "date", "boolean"}:
                new_type = old.type
            rename[old.name] = new_name
            new_cols.append(
                type(old)(
                    name=new_name,
                    type=new_type,
                    samples=old.samples,
                    source_name=getattr(old, "source_name", None) or old.name,
                )
            )
        new_rows = [{rename.get(k, k): v for k, v in row.items()} for row in rows]
        return new_cols, new_rows


def _resolve_path(ctx: RunContext, config: dict[str, Any]) -> Path:
    filename = str(config.get("filename") or "")
    raw = config.get("path") or config.get("file")
    candidates: list[Path] = []
    if raw:
        path = Path(str(raw))
        if not path.is_absolute():
            path = ctx.storage.path("uploads", str(raw))
        candidates.append(path)
        if filename:
            candidates.append(path.with_name(filename))
    if filename:
        candidates.append(ctx.storage.path("uploads", filename))
        pipelines = ctx.storage.path("pipelines")
        if pipelines.exists():
            candidates.extend(pipelines.glob(f"*/files/{filename}"))
    for path in candidates:
        if path.exists() and path.is_file():
            return path
    if candidates:
        raise ParseError(f"working file not found: {filename or raw}")
    raise ParseError("ingestion node config is missing 'path'")


registry.register(Ingestor)
