from __future__ import annotations

from app.agents.base import RunContext, registry
from app.models.envelope import Envelope
from app.services.exporter import (
    collect_streams,
    resolve_output_formats,
    resolve_theme,
    summarize,
    write_pdf,
    write_workbook,
)


class Exporter:
    """Write Excel/PDF artifacts onto the run snapshot. No alert dispatch."""

    name = "output"

    async def execute(self, ctx: RunContext, env: Envelope) -> list[Envelope]:
        config = dict(ctx.node.config) if ctx.node else {}
        theme = resolve_theme(config.get("theme"))
        title = str(config.get("title") or "Nexus Report")
        streams = collect_streams(ctx.inputs or [env], config)
        kpis = summarize(streams)
        formats = resolve_output_formats(
            config, node_mode=ctx.node.mode if ctx.node else None
        )
        charts = dict(config.get("charts") or {})
        node_id = ctx.node.id if ctx.node else env.node_id
        stem = str(config.get("filename") or f"{node_id}_{theme.id}")
        artifacts: list[str] = []
        written: dict[str, str] = {}

        if "xlsx" in formats:
            data = write_workbook(streams, theme=theme, title=title)
            rel = f"runs/{ctx.run_id}/artifacts/{stem}.xlsx"
            ctx.storage.write_bytes(data, *rel.split("/"))
            artifacts.append(rel)
            written["xlsx"] = rel
        if "pdf" in formats:
            data = write_pdf(streams, theme=theme, title=title, charts=charts)
            rel = f"runs/{ctx.run_id}/artifacts/{stem}.pdf"
            ctx.storage.write_bytes(data, *rel.split("/"))
            artifacts.append(rel)
            written["pdf"] = rel

        return [
            Envelope(
                run_id=ctx.run_id,
                node_id=node_id,
                port="default",
                payload={
                    "kind": "artifacts",
                    "formats": formats,
                    "theme": theme.id,
                    "title": title,
                    "kpis": kpis,
                    "tabs": [s.name for s in streams],
                    "artifacts": artifacts,
                    "files": written,
                    "delivered": True,
                },
                emitted_by="output@v1",
            )
        ]


registry.register(Exporter)
