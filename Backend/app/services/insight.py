from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Any

from app.core.llm import LLMError, LLMProvider
from app.models.pipeline import Pipeline
from app.models.run import Run


def _is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value.replace(",", "").replace("$", ""))
            return True
        except ValueError:
            return False
    return False


def to_number(value: Any) -> float | None:
    if not _is_number(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return float(str(value).replace(",", "").replace("$", ""))


def _is_date(value: Any) -> bool:
    if isinstance(value, (date, datetime)):
        return True
    if not isinstance(value, str) or not value:
        return False
    text = value[:10]
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return True
    return False


def rows_of(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows = (payload or {}).get("rows")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    return []


def use_case_profile(pipeline: Pipeline, run: Run) -> dict[str, Any]:
    meta = pipeline.meta or {}
    totals = 0
    ports: list[dict[str, Any]] = []
    for step in run.steps:
        for env in step.outputs:
            count = len(rows_of(env.payload or {}))
            totals += count
            ports.append(
                {
                    "node_id": step.node_id,
                    "agent": step.agent,
                    "port": env.port,
                    "row_count": count,
                    "status": step.status,
                }
            )
    return {
        "name": pipeline.name,
        "purpose": meta.get("purpose") or "",
        "brief": meta.get("brief") or "",
        "agents": [node.agent for node in pipeline.nodes],
        "ports": ports,
        "artifacts": list(run.artifacts or []),
        "status": run.status,
        "totals": totals,
    }


def group_sum(rows: list[dict[str, Any]], category: str, value: str | None, limit: int = 12) -> list[dict[str, Any]]:
    totals: Counter[str] = Counter()
    for row in rows:
        key = row.get(category)
        label = "(empty)" if key in (None, "") else str(key)
        if value:
            num = to_number(row.get(value))
            totals[label] += num or 0
        else:
            totals[label] += 1
    return [{"name": name, "value": round(val, 2)} for name, val in totals.most_common(limit)]


def variance(rows: list[dict[str, Any]], actual: str, expected: str, label: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    points = []
    for index, row in enumerate(rows):
        a = to_number(row.get(actual))
        e = to_number(row.get(expected))
        if a is None or e is None:
            continue
        name = str(row.get(label) or index + 1)
        points.append({"name": name, "actual": a, "expected": e, "value": round(a - e, 2)})
        if len(points) >= limit:
            break
    return points


def timeseries(rows: list[dict[str, Any]], date_field: str, value_field: str, limit: int = 40) -> list[dict[str, Any]]:
    buckets: dict[str, float] = defaultdict(float)
    for row in rows:
        raw = row.get(date_field)
        if raw in (None, ""):
            continue
        key = str(raw)[:10]
        num = to_number(row.get(value_field))
        if num is None:
            continue
        buckets[key] += num
    ordered = sorted(buckets.items())[:limit]
    return [{"name": name, "value": round(val, 2)} for name, val in ordered]


def column_stats(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    nums = [to_number(row.get(field)) for row in rows]
    nums = [n for n in nums if n is not None]
    if not nums:
        return {"count": 0, "total": 0, "min": None, "max": None, "mean": None}
    total = sum(nums)
    return {
        "count": len(nums),
        "total": round(total, 2),
        "min": round(min(nums), 2),
        "max": round(max(nums), 2),
        "mean": round(total / len(nums), 2),
    }


def rate(rows_a: list[dict[str, Any]], rows_b: list[dict[str, Any]]) -> dict[str, Any]:
    a = len(rows_a)
    b = len(rows_b)
    denom = a + b
    pct = round((a / denom) * 100, 1) if denom else 0.0
    return {"numerator": a, "denominator": denom, "value": pct}


def sparkline(rows: list[dict[str, Any]], field: str, limit: int = 12) -> list[float]:
    values = []
    for row in rows[:limit]:
        num = to_number(row.get(field))
        if num is not None:
            values.append(round(num, 2))
    return values


def date_columns(rows: list[dict[str, Any]], columns: list[str]) -> list[str]:
    found = []
    sample = rows[:20]
    for col in columns:
        values = [row.get(col) for row in sample if col in row]
        if values and all(_is_date(v) or v in (None, "") for v in values) and any(_is_date(v) for v in values):
            found.append(col)
    return found


def template_narrative(profile: dict[str, Any], facts: list[str]) -> str:
    name = profile.get("name") or "This pipeline"
    purpose = profile.get("purpose") or profile.get("brief") or "the saved use case"
    if isinstance(purpose, str) and "\n" in purpose:
        purpose = purpose.split("\n")[0][:180]
    parts = [f"{name} ran to {profile.get('status') or 'completion'} for {purpose}."]
    if facts:
        parts.append(" ".join(facts[:4]))
    else:
        parts.append(f"{profile.get('totals') or 0} output rows across {len(profile.get('ports') or [])} ports.")
    return " ".join(parts)


async def narrate(
    profile: dict[str, Any],
    facts: list[str],
    llm: LLMProvider | None = None,
) -> str:
    fallback = template_narrative(profile, facts)
    if not llm:
        return fallback
    prompt = (
        "Write 2-4 short sentences for a finance operations dashboard. "
        "Use only the facts given. Do not invent numbers or columns.\n\n"
        f"Use case: {profile.get('purpose') or profile.get('brief') or profile.get('name')}\n"
        f"Facts:\n" + "\n".join(f"- {item}" for item in facts)
    )
    try:
        text = (await llm.complete("reasoning", prompt, 0.2)).strip()
        return text or fallback
    except (LLMError, Exception):
        return fallback
