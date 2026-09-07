from __future__ import annotations

import asyncio

from app.agents.base import RunContext, registry
from app.models.envelope import Envelope
from app.services.decision import (
    POLICY_LLM_CAP,
    POLICY_LLM_TIMEOUT_SECONDS,
    collect_records,
    enrich_record,
    judge_record,
    passages_for,
    resolve_authority,
    resolve_mode,
    rule_verdict,
    split_ports,
    strip_meta,
)


class Decision:
    """Judgment, policy interpretation, and approval routing. Does not compute amounts."""

    name = "decision"

    async def execute(self, ctx: RunContext, env: Envelope) -> list[Envelope]:
        config = dict(ctx.node.config) if ctx.node else {}
        mode = resolve_mode(config.get("mode") or (ctx.node.mode if ctx.node else None))
        authority = resolve_authority(config.get("authority"))
        threshold = float(config.get("confidence_threshold", 0.85))
        policy = str(config.get("policy") or "").strip()
        temperature = float(config.get("temperature", 0.1))
        limit = int(config.get("max_chunks", 3))
        records = collect_records(ctx.inputs or [env])
        judged: list[tuple | None] = [None] * len(records)
        mail_indexes = [i for i, record in enumerate(records) if record.get("mail_id")]
        judge_timeout = 20.0 if mail_indexes else 8.0
        batch_timeout = 60.0 if mail_indexes else POLICY_LLM_TIMEOUT_SECONDS

        async def _judge(index: int, record: dict) -> None:
            clean = strip_meta(record)
            passages = passages_for(ctx.knowledge_store, clean, policy, limit=limit)
            try:
                raw = await asyncio.wait_for(
                    judge_record(
                        ctx.llm,
                        clean,
                        mode=mode,
                        policy=policy,
                        passages=passages,
                        temperature=temperature,
                    ),
                    timeout=judge_timeout,
                )
            except (TimeoutError, asyncio.TimeoutError):
                raw = rule_verdict(record, policy)
                passages = []
            judged[index] = enrich_record(
                clean,
                raw,
                mode=mode,
                authority=authority,
                threshold=threshold,
                passages=passages,
                knowledge=ctx.knowledge_store,
            )

        llm_indexes = list(range(min(len(records), POLICY_LLM_CAP))) if policy else []
        llm_indexes = sorted(set(llm_indexes) | set(mail_indexes[:POLICY_LLM_CAP]))
        for i, record in enumerate(records):
            if i in llm_indexes:
                continue
            clean = strip_meta(record)
            judged[i] = enrich_record(
                clean,
                rule_verdict(record, policy),
                mode=mode,
                authority=authority,
                threshold=threshold,
                passages=[],
                knowledge=ctx.knowledge_store,
            )

        if llm_indexes:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*(_judge(i, records[i]) for i in llm_indexes)),
                    timeout=batch_timeout,
                )
            except (TimeoutError, asyncio.TimeoutError):
                for i in llm_indexes:
                    if judged[i] is None:
                        clean = strip_meta(records[i])
                        judged[i] = enrich_record(
                            clean,
                            rule_verdict(records[i], policy),
                            mode=mode,
                            authority=authority,
                            threshold=threshold,
                            passages=[],
                            knowledge=ctx.knowledge_store,
                        )

        items = [item for item in judged if item is not None]
        from app.services.mail import attach_drafts_llm, flatten_mail_row

        flattened: list[tuple] = []
        for port, row in items:
            flattened.append((port, flatten_mail_row(row)))
        if any(row.get("mail_id") for _, row in flattened):
            drafted = await attach_drafts_llm([row for _, row in flattened], ctx.llm)
            flattened = [(flattened[i][0], drafted[i]) for i in range(len(flattened))]
        items = flattened
        ports = split_ports(items)
        node_id = ctx.node.id if ctx.node else env.node_id
        envelopes: list[Envelope] = []
        for port, rows in ports.items():
            if not rows:
                continue
            envelopes.append(
                Envelope(
                    run_id=ctx.run_id,
                    node_id=node_id,
                    port=port,
                    payload={
                        "kind": "decisions",
                        "rows": rows,
                        "mode": mode,
                        "authority": authority,
                    },
                    emitted_by="decision@v1",
                )
            )
        return envelopes


registry.register(Decision)
