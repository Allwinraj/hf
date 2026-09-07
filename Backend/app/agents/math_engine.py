from __future__ import annotations

import re
from decimal import ROUND_HALF_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from app.agents.base import RunContext, registry
from app.engine.ast_sandbox import SandboxError, eval_expr
from app.models.envelope import Envelope
from app.services.formulas import compile_logic
from app.services.matching import flatten_record, get_bound

_ROUND = {
    "half_up": ROUND_HALF_UP,
    "half_down": ROUND_HALF_DOWN,
    "nearest": ROUND_HALF_EVEN,
}


class MathEngine:
    """Deterministic rules and math. LLM is used only to compile, never to calculate."""

    name = "math"

    async def execute(self, ctx: RunContext, env: Envelope) -> list[Envelope]:
        config = dict(ctx.node.config) if ctx.node else {}
        rows = _rows(env, ctx)
        logic = await compile_logic(config, ctx.llm)
        shape = config.get("shape") or logic.shape
        mode = config.get("mode") or logic.mode
        output = config.get("output_column") or logic.output
        input_map = dict(config.get("input_map") or logic.input_map or {})
        constants = {
            k: _to_dec(v)
            for k, v in {**dict(logic.constants or {}), **dict(config.get("constants") or {})}.items()
        }
        empty_rule = dict(config.get("empty_rule") or {})
        precision = int(config.get("precision", 2))
        rounding = str(config.get("rounding") or "half_up")
        group_by = list(config.get("group_by") or logic.group_by or [])
        aggregate_output = config.get("aggregate_output") or "summary"
        opening = _to_dec(config.get("opening_balance") or 0)

        if shape == "sequential":
            result_rows = _sequential(
                rows, logic, output, input_map, empty_rule, precision, rounding, opening, mode, constants
            )
        elif shape == "aggregate":
            result_rows = _aggregate(
                rows,
                logic,
                output,
                input_map,
                empty_rule,
                precision,
                rounding,
                group_by,
                aggregate_output,
                mode,
                constants,
            )
        elif shape == "scalar":
            result_rows = _scalar(
                rows, logic, output, input_map, empty_rule, precision, rounding, mode, constants
            )
        else:
            result_rows = _per_row(
                rows, logic, output, input_map, empty_rule, precision, rounding, mode, constants
            )

        return [
            Envelope(
                run_id=ctx.run_id,
                node_id=ctx.node.id if ctx.node else env.node_id,
                port="default",
                payload={
                    "kind": "table",
                    "rows": result_rows,
                    "logic": {
                        "catalog_id": logic.catalog_id,
                        "ast": logic.ast,
                        "gate_ast": logic.gate_ast,
                        "mode": mode,
                        "shape": shape,
                        "output": output,
                        "input_map": input_map,
                        "constants": {str(k): str(v) for k, v in constants.items()},
                    },
                },
                emitted_by="math@v1",
            )
        ]


def _rows(env: Envelope, ctx: RunContext) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    data: list[dict[str, Any]] = []
    other: list[dict[str, Any]] = []
    for incoming in ctx.inputs or [env]:
        payload = incoming.payload or {}
        rows = payload.get("rows")
        if not isinstance(rows, list) or not rows:
            continue
        copied = [dict(r) for r in rows if isinstance(r, dict)]
        kind = str(payload.get("kind") or "")
        if kind == "matches" or incoming.port == "matched":
            matched.extend(copied)
        elif kind == "data":
            data.extend(copied)
        else:
            other.extend(copied)
    raw = matched or other or data
    return [flatten_record(r) for r in raw]


def _per_row(rows, logic, output, input_map, empty_rule, precision, rounding, mode, constants):
    out = []
    for row in rows:
        item = dict(row)
        names = _names(item, input_map, constants)
        if _missing_formula_inputs(logic, names):
            item[output] = empty_rule.get("result") if empty_rule else None
            item["skipped"] = True
            item["flag"] = False
            out.append(item)
            continue
        skipped = _apply_empty(item, names, empty_rule, output)
        if skipped:
            out.append(item)
            continue
        try:
            if mode in {"calculation", "hybrid"}:
                item[output] = _round(eval_expr(logic.ast, names), precision, rounding)
                names[output] = _to_dec(item[output])
            if mode in {"rule", "hybrid"} and logic.gate_ast:
                item["flag"] = bool(eval_expr(logic.gate_ast, names))
            elif mode == "rule":
                item["flag"] = bool(eval_expr(logic.ast, names))
        except (SandboxError, InvalidOperation, ZeroDivisionError, KeyError, TypeError) as exc:
            item["error"] = str(exc)
            item[output] = empty_rule.get("result", "—")
        out.append(item)
    return out


def _sequential(rows, logic, output, input_map, empty_rule, precision, rounding, opening, mode, constants):
    previous = opening
    out = []
    for row in rows:
        item = dict(row)
        names = _cash_aliases(_names(item, input_map, constants))
        names["previous"] = previous
        skipped = _apply_empty(item, names, empty_rule, output)
        if skipped:
            item[output] = previous
            out.append(item)
            continue
        try:
            value = _round(eval_expr(logic.ast, names), precision, rounding)
            item[output] = value
            previous = _to_dec(value) if isinstance(value, Decimal) else previous
            if mode in {"rule", "hybrid"} and logic.gate_ast:
                names[output] = previous
                item["flag"] = bool(eval_expr(logic.gate_ast, names))
        except (SandboxError, InvalidOperation, ZeroDivisionError, TypeError) as exc:
            item["error"] = str(exc)
            item[output] = empty_rule.get("result", "—")
        out.append(item)
    return out


def _aggregate(
    rows, logic, output, input_map, empty_rule, precision, rounding, group_by, aggregate_output, mode, constants
):
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for row in rows:
        key = tuple(row.get(col) for col in group_by) if group_by else (("_all",),)
        groups.setdefault(key, []).append(row)
    summaries = []
    totals: dict[tuple, Any] = {}
    for key, group in groups.items():
        names = _group_names(group, input_map, constants)
        try:
            totals[key] = _round(eval_expr(logic.ast, names), precision, rounding)
        except (SandboxError, InvalidOperation, ZeroDivisionError) as exc:
            totals[key] = empty_rule.get("result", "—")
            err = str(exc)
        else:
            err = None
        summary = {col: key[i] for i, col in enumerate(group_by)} if group_by else {}
        summary[output] = totals[key]
        if err:
            summary["error"] = err
        if mode in {"rule", "hybrid"} and logic.gate_ast:
            names[output] = _to_dec(totals[key])
            summary["flag"] = bool(eval_expr(logic.gate_ast, names))
        summaries.append(summary)
    if aggregate_output == "window":
        windowed = []
        for row in rows:
            key = tuple(row.get(col) for col in group_by) if group_by else (("_all",),)
            item = dict(row)
            item[output] = totals[key]
            windowed.append(item)
        return windowed
    return summaries


def _scalar(rows, logic, output, input_map, empty_rule, precision, rounding, mode, constants):
    names = _group_names(rows, input_map, constants)
    try:
        value = _round(eval_expr(logic.ast, names), precision, rounding)
        row = {output: value}
        if mode in {"rule", "hybrid"} and logic.gate_ast:
            names[output] = _to_dec(value)
            row["flag"] = bool(eval_expr(logic.gate_ast, names))
        return [row]
    except (SandboxError, InvalidOperation, ZeroDivisionError) as exc:
        return [{output: empty_rule.get("result", "—"), "error": str(exc)}]


def _group_names(
    group: list[dict[str, Any]], input_map: dict[str, str], constants: dict[str, Any] | None = None
) -> dict[str, Any]:
    cols: set[str] = set()
    for row in group:
        cols.update(row.keys())
        cols.update(input_map.keys())
    names: dict[str, Any] = {"count": len(group)}
    names.update(constants or {})
    for col in cols:
        series = []
        for row in group:
            source = input_map.get(col, col)
            series.append(_to_dec(row.get(source, row.get(col))))
        names[col] = [v for v in series if v is not None]
    for canon, source in input_map.items():
        names[canon] = [v for v in (_to_dec(row.get(source)) for row in group) if v is not None]
    return names


def _names(
    row: dict[str, Any], input_map: dict[str, str], constants: dict[str, Any] | None = None
) -> dict[str, Any]:
    names = {key: _to_dec(value) for key, value in row.items()}
    names.update(constants or {})
    for canon, source in input_map.items():
        names[canon] = _to_dec(row.get(source, get_bound(row, source)))
    for canon in ("actual", "budget", "expected", "amount", "deposit", "withdrawal", "measure"):
        if names.get(canon) is None:
            bound = get_bound(row, canon)
            if bound is not None:
                names[canon] = _to_dec(bound)
    if names.get("actual") is None:
        for cand in ("amount_received", "paid_amount", "amount"):
            bound = get_bound(row, cand)
            if bound is not None:
                names["actual"] = _to_dec(bound)
                break
    if names.get("expected") is None:
        for cand in ("invoice_total", "total_amount", "invoice_amount"):
            bound = get_bound(row, cand)
            if bound is not None:
                names["expected"] = _to_dec(bound)
                break
    return names


def _apply_empty(item: dict[str, Any], names: dict[str, Any], empty_rule: dict, output: str) -> bool:
    if not empty_rule:
        return False
    field = empty_rule.get("on")
    if not field:
        return False
    value = names.get(field, names.get(empty_rule.get("on")))
    trigger = empty_rule.get("when") or "missing"
    missing = value is None or value == "" or value == "—"
    zero = isinstance(value, Decimal) and value == 0
    hit = (trigger == "missing" and missing) or (
        trigger == "zero_or_missing" and (missing or zero)
    )
    if hit:
        item[output] = empty_rule.get("result", "—")
        item["skipped"] = True
        return True
    return False


def _missing_formula_inputs(logic, names: dict[str, Any]) -> bool:
    text = f"{getattr(logic, 'ast', '')} {getattr(logic, 'gate_ast', '') or ''}"
    for name in ("actual", "expected"):
        if re.search(rf"\b{name}\b", text) and names.get(name) is None:
            return True
    return False


def _cash_aliases(names: dict[str, Any]) -> dict[str, Any]:
    if names.get("deposit") is None and names.get("withdrawal") is None:
        amt = names.get("amount")
        if isinstance(amt, Decimal):
            names["deposit"] = amt if amt >= 0 else Decimal("0")
            names["withdrawal"] = -amt if amt < 0 else Decimal("0")
    if names.get("deposit") is None:
        names["deposit"] = Decimal("0")
    if names.get("withdrawal") is None:
        names["withdrawal"] = Decimal("0")
    return names


def _to_dec(value: Any) -> Any:
    if value is None or value == "" or value == "—":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    text = str(value).strip().replace(",", "").replace("$", "")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return value


def _round(value: Any, precision: int, rounding: str) -> Any:
    if not isinstance(value, Decimal):
        return value
    mode = _ROUND.get(rounding, ROUND_HALF_UP)
    if precision <= 0:
        quant = Decimal("1")
    else:
        quant = Decimal("1").scaleb(-precision)
    return value.quantize(quant, rounding=mode)


registry.register(MathEngine)
