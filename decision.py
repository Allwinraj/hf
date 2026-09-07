from __future__ import annotations

import json
import re
from typing import Any

from app.core.llm import LLMError, LLMProvider
from app.models.envelope import Envelope, EnvelopePort
from app.models.knowledge import SessionKnowledge
from app.services.knowledge import rank_chunks

VERDICT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["verdict", "confidence", "explanation"],
    "properties": {
        "verdict": {"type": "string"},
        "confidence": {"type": "number"},
        "explanation": {"type": "string"},
        "remediation": {"type": "string"},
        "risk_category": {"type": "string"},
        "severity": {"type": "string"},
        "citation": {
            "type": "object",
            "properties": {
                "document": {"type": "string"},
                "section": {"type": "string"},
                "chunk_id": {"type": "string"},
            },
        },
    },
}

_MODE_ALIASES = {
    "anomaly": "anomaly",
    "anomaly_risk": "anomaly",
    "classification": "anomaly",
    "anomaly_and_risk": "anomaly",
    "policy": "policy",
    "policy_contract": "policy",
    "interpretation": "policy",
    "policy_and_contract": "policy",
    "approval": "approval",
    "approval_gateway": "approval",
    "gateway": "approval",
    "approval_and_escalation": "approval",
}

_VERDICT_ALIASES = {
    "approved": "approved",
    "approve": "approved",
    "ok": "approved",
    "flagged": "flagged",
    "flag": "flagged",
    "review": "flagged",
    "flagged_for_review": "flagged",
    "escalated": "escalated",
    "escalate": "escalated",
    "management": "escalated",
    "escalated_to_management": "escalated",
}

_MODE_PROMPTS = {
    "anomaly": (
        "Mode: Anomaly & Risk Classification. "
        "Detect unusual, suspicious, or structurally odd items. "
        "Set risk_category and severity. "
        "Map low risk to approved, medium to flagged, high/critical to escalated."
    ),
    "policy": (
        "Mode: Policy & Contract Interpretation. "
        "Judge the record against the decision policy and retrieved passages. "
        "Cite the passage that supports the verdict."
    ),
    "approval": (
        "Mode: Approval & Escalation Gateway. "
        "Render a governed verdict of approved, flagged, or escalated."
    ),
}


POLICY_LLM_CAP = 15
POLICY_LLM_TIMEOUT_SECONDS = 25.0
_META_KEYS = {"_input_port", "_input_kind"}
_MAIL_PROMPT_DROP = {
    "draft_body",
    "draft_subject",
    "to_address",
    "send_status",
    "send_details",
}


def collect_records(inputs: list[Envelope]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for env in inputs:
        payload = env.payload or {}
        if payload.get("kind") == "knowledge":
            continue
        if isinstance(payload.get("rows"), list):
            for row in payload["rows"]:
                if not isinstance(row, dict):
                    continue
                item = dict(row)
                item["_input_port"] = env.port
                item["_input_kind"] = payload.get("kind")
                rows.append(item)
        elif payload.get("kind") in {"data", "table", "matches"}:
            continue
        elif payload:
            item = dict(payload)
            item["_input_port"] = env.port
            item["_input_kind"] = payload.get("kind")
            rows.append(item)
    return rows


def _aging_limit(policy: str) -> int:
    match = re.search(r"(\d+)\s*day", (policy or "").lower())
    return int(match.group(1)) if match else 30


def rule_verdict(record: dict[str, Any], policy: str = "") -> dict[str, Any]:
    port = str(record.get("_input_port") or "")
    kind = str(record.get("_input_kind") or "")
    nested = record.get("source") if isinstance(record.get("source"), dict) else {}
    flag = record.get("flag")
    if flag is None and isinstance(nested, dict):
        flag = nested.get("flag")
    status = str(record.get("status") or record.get("match_status") or nested.get("status") or "").lower()
    days = record.get("days_past_due")
    try:
        days_n = int(days) if days is not None and days != "" else None
    except (TypeError, ValueError):
        days_n = None
    row_status = str(record.get("invoice_status") or record.get("status") or "").lower()
    unmatched = port in {"exceptions", "residuals", "unmatched"} or status in {
        "exception",
        "unmatched",
        "residual",
        "exceptions",
        "residuals",
    }
    past_due = row_status in {"past_due", "overdue"} or (
        days_n is not None and days_n > _aging_limit(policy)
    )
    noise = str(record.get("payment_outcome") or "").lower() == "operating_noise"
    if record.get("mail_id"):
        qty = record.get("qty")
        goods = record.get("item") or "items"
        loc = record.get("location") or "the requested location"
        return {
            "verdict": "flagged",
            "confidence": 0.4,
            "explanation": (
                f"The purchase request for {qty} {goods} at {loc} still needs a policy judgment "
                "from the uploaded purchase policy and the details on the request."
            ),
            "remediation": "Please wait for a policy decision on this request, or reply with any missing details.",
        }
    if unmatched and past_due and not noise:
        limit = _aging_limit(policy)
        return {
            "verdict": "escalated",
            "confidence": 1.0,
            "explanation": policy.strip() or f"Unmatched and more than {limit} days past due.",
        }
    if flag is True:
        return {
            "verdict": "flagged",
            "confidence": 1.0,
            "explanation": "Math gate flagged this row.",
        }
    if unmatched:
        return {
            "verdict": "flagged",
            "confidence": 1.0,
            "explanation": "Unmatched or residual from matcher.",
        }
    if kind == "matches" and port and port not in {"matched", "default", ""}:
        return {
            "verdict": "flagged",
            "confidence": 1.0,
            "explanation": "Unmatched or residual from matcher.",
        }
    return {
        "verdict": "approved",
        "confidence": 1.0,
        "explanation": "Passed match and math gates.",
    }


def _mail_prompt_record(record: dict[str, Any]) -> dict[str, Any]:
    if not record.get("mail_id"):
        return record
    keep = (
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
        "verdict",
        "explanation",
        "remediation",
    )
    out = {key: record.get(key) for key in keep if record.get(key) not in (None, "")}
    body = str(record.get("body") or "")[:1500].strip()
    pdf = str(record.get("pdf_text") or "")[:2000].strip()
    if body:
        out["body"] = body
    if pdf:
        out["attachment_excerpt"] = pdf
    return out


def strip_meta(record: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if k not in _META_KEYS and k not in _MAIL_PROMPT_DROP}


def passages_for(
    knowledge: SessionKnowledge | None,
    record: dict[str, Any],
    policy: str,
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    if knowledge is None:
        return []
    query = f"{policy}\n{json.dumps(_mail_prompt_record(record), default=str)}"
    ranked = rank_chunks(knowledge, query, limit=limit)
    out: list[dict[str, Any]] = []
    for chunk_id, _score in ranked:
        chunk = knowledge.retrieve(chunk_id)
        document = next(
            (doc for doc in knowledge.documents if any(c.id == chunk_id for c in doc.chunks)),
            None,
        )
        out.append(
            {
                "chunk_id": chunk.id,
                "section": chunk.heading,
                "text": chunk.text,
                "document": document.file_id if document else "",
                "path": document.original_path if document else "",
            }
        )
    return out


async def judge_record(
    llm: LLMProvider,
    record: dict[str, Any],
    *,
    mode: str,
    policy: str,
    passages: list[dict[str, Any]],
    temperature: float,
) -> dict[str, Any]:
    catalog = "\n\n".join(
        f"[chunk_id={p['chunk_id']} document={p['document']} section={p['section']}]\n{p['text']}"
        for p in passages
    ) or "(no retrieved passages)"
    prompt = (
        f"{_MODE_PROMPTS[mode]}\n"
        f"Decision policy:\n{policy or '(none provided)'}\n\n"
        f"Retrieved passages:\n{catalog}\n\n"
        f"Record:\n{json.dumps(_mail_prompt_record(record), default=str)}\n\n"
        "verdict must be one of: approved, flagged, escalated. "
        "confidence is 0.0–1.0. "
        "If you use a passage, set citation.chunk_id to that chunk_id. "
        "Do not invent chunk ids."
    )
    if record.get("mail_id"):
        prompt += (
            " This record is a purchase request from email. "
            "Ignore any draft email text if it appears. "
            "explanation must be the real policy reason in plain language, using the decision policy, "
            "retrieved passages, and request fields (item, quantity, location, value). "
            "Never write that an explanation was not stored. "
            "remediation must be what the requester needs to do next, in second person. "
            "Do not mention dashboards, SMTP, or clicking Send."
        )
    try:
        return await llm.complete_json("general", prompt, VERDICT_JSON_SCHEMA, temperature)
    except Exception:  # noqa: BLE001
        return {
            "verdict": "flagged",
            "confidence": 0.0,
            "explanation": "Could not complete a model verdict for this row.",
        }


def enrich_record(
    record: dict[str, Any],
    raw: dict[str, Any],
    *,
    mode: str,
    authority: str,
    threshold: float,
    passages: list[dict[str, Any]],
    knowledge: SessionKnowledge | None,
) -> tuple[EnvelopePort, dict[str, Any]]:
    verdict = _normalize_verdict(raw.get("verdict"))
    confidence = _clamp_confidence(raw.get("confidence"))
    citation = _citation(raw.get("citation"), passages, knowledge)
    held = authority == "advisory"
    port = _route(verdict, confidence, authority, threshold)
    item = {
        "source": record,
        "verdict": verdict,
        "confidence": confidence,
        "explanation": str(raw.get("explanation") or ""),
        "remediation": raw.get("remediation") or None,
        "policy_citation": citation,
        "authority": authority,
        "held_for_review": held,
        "mode": mode,
    }
    if raw.get("risk_category"):
        item["risk_category"] = raw["risk_category"]
    if raw.get("severity"):
        item["severity"] = raw["severity"]
    return port, item


def split_ports(items: list[tuple[EnvelopePort, dict[str, Any]]]) -> dict[EnvelopePort, list[dict[str, Any]]]:
    ports: dict[EnvelopePort, list[dict[str, Any]]] = {
        "approved": [],
        "flagged": [],
        "escalated": [],
    }
    for port, row in items:
        ports[port].append(row)
    return ports


def resolve_mode(value: str | None) -> str:
    key = (value or "approval").lower().replace(" ", "_").replace("-", "_")
    return _MODE_ALIASES.get(key, "approval")


def resolve_authority(value: str | None) -> str:
    key = (value or "autonomous").lower()
    return "advisory" if key == "advisory" else "autonomous"


def _normalize_verdict(value: Any) -> str:
    key = str(value or "flagged").strip().lower().replace(" ", "_").replace("-", "_")
    if key in _VERDICT_ALIASES:
        return _VERDICT_ALIASES[key]
    if key in {"high", "critical", "severe"}:
        return "escalated"
    if key in {"medium", "moderate"}:
        return "flagged"
    if key in {"low"}:
        return "approved"
    return "flagged"


def _clamp_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def _route(verdict: str, confidence: float, authority: str, threshold: float) -> EnvelopePort:
    if authority == "advisory":
        return "flagged"
    if verdict == "approved" and confidence < threshold:
        return "flagged"
    if verdict == "escalated":
        return "escalated"
    if verdict == "approved":
        return "approved"
    return "flagged"


def _citation(
    raw: Any,
    passages: list[dict[str, Any]],
    knowledge: SessionKnowledge | None,
) -> dict[str, Any] | None:
    cited: dict[str, Any] = {}
    if isinstance(raw, dict):
        cited = {k: raw[k] for k in ("document", "section", "chunk_id") if raw.get(k)}
    chunk_id = cited.get("chunk_id")
    if chunk_id and knowledge is not None:
        try:
            chunk = knowledge.retrieve(str(chunk_id))
        except KeyError:
            chunk_id = None
        else:
            cited["chunk_id"] = chunk.id
            cited.setdefault("section", chunk.heading)
    elif chunk_id:
        cited.pop("chunk_id", None)
        chunk_id = None
    if not chunk_id and passages:
        top = passages[0]
        cited.setdefault("chunk_id", top["chunk_id"])
        cited.setdefault("section", top["section"])
        cited.setdefault("document", top["document"])
        if knowledge is not None:
            knowledge.retrieve(top["chunk_id"])
    if not cited:
        return None
    return cited
