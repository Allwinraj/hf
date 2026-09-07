from __future__ import annotations

from typing import Any

CATALOG: list[dict[str, Any]] = [
    {
        "name": "ingestion",
        "label": "Ingestion",
        "summary": "Parse working data or knowledge documents into envelopes.",
        "modes": ["data", "knowledge", "mailbox"],
        "ports": {"out": ["default"]},
        "config_schema": {
            "mode": {
                "type": "enum",
                "values": ["data", "knowledge", "mailbox"],
                "read_only": True,
                "description": "Data vs Knowledge — set from upload intent.",
            },
            "path": {"type": "string", "section": "file", "description": "File name / path"},
            "sheet": {"type": "string", "section": "file", "description": "Excel sheet"},
            "header_row": {"type": "integer", "section": "file"},
            "schema": {"type": "array", "section": "schema", "expandable": True},
            "schema_overrides": {"type": "object", "section": "schema", "expandable": True},
            "model": {"type": "string", "section": "advanced"},
            "temperature": {"type": "number", "section": "advanced"},
        },
    },
    {
        "name": "matcher",
        "label": "Matcher",
        "summary": "Find and score related records. Does not apply amount tolerances.",
        "modes": ["dedupe", "structural", "semantic"],
        "ports": {"out": ["matched", "residuals", "exceptions"]},
        "config_schema": {
            "mode": {
                "type": "enum",
                "values": ["dedupe", "structural", "semantic"],
            },
            "keys": {
                "type": "array",
                "items": "string",
                "section": "keys",
                "hidden_when_mode": ["dedupe"],
                "description": "Columns used to align records.",
            },
            "confidence_threshold": {
                "type": "number",
                "section": "semantic",
                "hidden_when_mode": ["dedupe", "structural"],
            },
            "window_days": {"type": "integer", "section": "advanced"},
            "flags": {
                "type": "object",
                "section": "advanced",
                "properties": [
                    "directional",
                    "allocation",
                    "group_receipts",
                    "receipts_only",
                    "residual",
                    "reversal",
                    "keyless",
                    "distinct_guard",
                ],
            },
            "model": {"type": "string", "section": "advanced"},
            "temperature": {"type": "number", "section": "advanced"},
        },
    },
    {
        "name": "math",
        "label": "Rules & Math",
        "summary": "Deterministic calculation and gates. Numeric tolerances live here.",
        "modes": ["calculation", "rule", "hybrid"],
        "ports": {"out": ["default"]},
        "config_schema": {
            "mode": {"type": "enum", "values": ["calculation", "rule", "hybrid"]},
            "formula_en": {"type": "string", "section": "formula"},
            "catalog_id": {"type": "string", "section": "formula"},
            "shape": {
                "type": "enum",
                "values": ["per_row", "aggregate", "sequential", "scalar"],
            },
            "output_column": {"type": "string"},
            "input_map": {"type": "object", "section": "inputs"},
            "precision": {"type": "integer"},
            "rounding": {"type": "enum", "values": ["half_up", "half_down", "nearest"]},
            "empty_rule": {"type": "object"},
            "ast": {"type": "string", "section": "inspector"},
            "gate_ast": {"type": "string", "section": "inspector"},
            "error_strategy": {
                "type": "enum",
                "values": ["fail_fast", "emit_exceptions"],
            },
        },
    },
    {
        "name": "decision",
        "label": "Decision",
        "summary": "Judgment, policy interpretation, and approval routing.",
        "modes": ["anomaly", "policy", "approval"],
        "ports": {"out": ["approved", "flagged", "escalated"]},
        "config_schema": {
            "mode": {
                "type": "enum",
                "values": ["anomaly", "policy", "approval"],
            },
            "policy": {"type": "string", "section": "policy"},
            "authority": {"type": "enum", "values": ["autonomous", "advisory"]},
            "confidence_threshold": {"type": "number", "default": 0.85},
            "temperature": {"type": "number", "section": "advanced", "default": 0.1},
            "model": {"type": "string", "section": "advanced"},
        },
    },
    {
        "name": "output",
        "label": "Output",
        "summary": "Excel and PDF artifacts for local download. No alert dispatch in v1.",
        "modes": ["excel", "pdf", "both"],
        "ports": {"out": ["default"]},
        "config_schema": {
            "mode": {"type": "enum", "values": ["excel", "pdf", "both"]},
            "title": {"type": "string"},
            "filename": {"type": "string"},
            "tabs": {"type": "object", "description": "Upstream stream labels"},
            "charts": {
                "type": "object",
                "properties": ["donut", "variance", "trend"],
            },
            "theme": {
                "type": "enum",
                "values": ["executive_classic", "modern_slate", "audit_clean"],
            },
            "formats": {"type": "array", "items": "string"},
        },
    },
]


def catalog_entry(name: str) -> dict[str, Any] | None:
    for item in CATALOG:
        if item["name"] == name:
            return item
    return None
