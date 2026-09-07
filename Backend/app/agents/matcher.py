from __future__ import annotations

from app.agents.base import RunContext, registry
from app.models.envelope import Envelope
from app.services.matching import collect_sources, run_match, split_ports


class Matcher:
    """Find and score related records. Does not apply amount/variance tolerances."""

    name = "matcher"

    async def execute(self, ctx: RunContext, env: Envelope) -> list[Envelope]:
        config = dict(ctx.node.config) if ctx.node else {}
        tables = collect_sources(ctx.inputs or [env])
        records = await run_match(config, tables, ctx.llm)
        ports = split_ports(records)
        node_id = ctx.node.id if ctx.node else env.node_id
        envelopes: list[Envelope] = []
        for port, rows in ports.items():
            if not rows:
                continue
            envelopes.append(
                Envelope(
                    run_id=ctx.run_id,
                    node_id=node_id,
                    port=port,  # type: ignore[arg-type]
                    payload={"kind": "matches", "rows": rows, "mode": config.get("mode")},
                    emitted_by="matcher@v1",
                )
            )
        return envelopes


registry.register(Matcher)
