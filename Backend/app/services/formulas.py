from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from app.core.llm import LLMError
from app.core.settings import BACKEND_ROOT
from app.engine.ast_sandbox import validate_expr

logger = logging.getLogger("nexus.formulas")

SELECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["catalog_id"],
    "properties": {
        "catalog_id": {"type": "string"},
        "constants": {"type": "object"},
        "input_map": {"type": "object"},
    },
}


class CatalogFormula(BaseModel):
    id: str
    description: str = ""
    aliases: list[str] = Field(default_factory=list)
    mode: str = "calculation"
    shape: str = "per_row"
    output: str = "result"
    inputs: list[str] = Field(default_factory=list)
    ast: str
    gate_ast: str | None = None
    slots: dict[str, Any] = Field(default_factory=dict)
    input_hints: dict[str, list[str]] = Field(default_factory=dict)
    group_by: list[str] = Field(default_factory=list)


class FormulaCatalog(BaseModel):
    version: str
    formulas: list[CatalogFormula]

    def get(self, formula_id: str) -> CatalogFormula:
        for item in self.formulas:
            if item.id == formula_id:
                return item
        raise KeyError(formula_id)

    def ids(self) -> list[str]:
        return [item.id for item in self.formulas]


@lru_cache
def load_catalog(path: str | None = None) -> FormulaCatalog:
    file = Path(path) if path else BACKEND_ROOT / "data" / "formulas" / "v1.yaml"
    data = yaml.safe_load(file.read_text(encoding="utf-8"))
    catalog = FormulaCatalog.model_validate(data)
    for item in catalog.formulas:
        _assert_safe(item.ast)
        if item.gate_ast:
            _assert_safe(item.gate_ast)
    return catalog


def catalog_digest(path: str | None = None) -> str:
    catalog = load_catalog(path)
    lines = []
    for item in catalog.formulas:
        slot_names = ",".join(item.slots.keys()) or "none"
        lines.append(f"{item.id}: {item.description} (slots: {slot_names})")
    return "\n".join(lines)


_FORMULA_HINTS = (
    "%",
    "percent",
    "tolerance",
    "variance",
    "whichever",
    "lesser",
    "greater",
    "smaller",
    "larger",
    "$",
    "dollar",
    "usd",
    "running balance",
    "deposit",
    "withdrawal",
    "previous plus",
    "net break",
    "material",
)


def looks_like_formula_answer(text: str) -> bool:
    lower = str(text or "").lower()
    return any(token in lower for token in _FORMULA_HINTS)


def math_phrase_from_session(session: Any) -> str:
    """Recover the user's tolerance/formula words when a model omitted formula_en."""
    for req in getattr(session, "requirements", []) or []:
        if str(getattr(req, "kind", "")).lower() not in {"math", "formula", "gate", "variance"}:
            continue
        value = dict(getattr(req, "value", None) or {})
        if value.get("formula_en"):
            return str(value["formula_en"])
        if value.get("catalog_id"):
            return str(value["catalog_id"])
    for msg in reversed(getattr(session, "messages", []) or []):
        if getattr(msg, "role", "") == "user" and looks_like_formula_answer(getattr(msg, "content", "")):
            return str(msg.content).strip()
    desc = str((getattr(session, "extra", None) or {}).get("description") or "")
    if looks_like_formula_answer(desc):
        return desc
    return ""


def compile_math_value_sync(value: dict[str, Any]) -> dict[str, Any]:
    """Hydrate math from the catalog without calling an LLM."""
    cfg = dict(value or {})
    phrase = str(cfg.get("formula_en") or cfg.get("formula") or "").strip()
    if not phrase and cfg.get("catalog_id"):
        hydrated = hydrate_math_config(cfg)
        return hydrated if hydrated.get("ast") else cfg
    if not phrase:
        return cfg
    catalog = load_catalog(cfg.get("catalog_path"))
    inferred = infer_logic_from_english(phrase, catalog, cfg)
    if inferred is None:
        hydrated = hydrate_math_config({**cfg, "formula_en": phrase})
        return hydrated if hydrated.get("ast") else cfg
    return logic_to_config({**cfg, "formula_en": phrase}, inferred)


def _assert_safe(expression: str) -> None:
    validate_expr(expression)


class CompiledLogic(BaseModel):
    catalog_id: str | None = None
    ast: str
    gate_ast: str | None = None
    shape: str = "per_row"
    mode: str = "calculation"
    output: str = "result"
    inputs: list[str] = Field(default_factory=list)
    constants: dict[str, Any] = Field(default_factory=dict)
    input_map: dict[str, str] = Field(default_factory=dict)
    group_by: list[str] = Field(default_factory=list)


def infer_logic_from_english(
    english: str, catalog: FormulaCatalog, config: dict[str, Any]
) -> CompiledLogic | None:
    item = _match_catalog_item(str(english), catalog, config)
    if item is None:
        return None
    constants = fill_slots_from_english(str(english), item, dict(config.get("constants") or {}))
    if config.get("threshold") is not None and "amount" in item.slots:
        constants.setdefault("amount", config["threshold"])
    return _logic_from_catalog(item, config, constants=constants)


def _match_catalog_item(
    english: str, catalog: FormulaCatalog, config: dict[str, Any]
) -> CatalogFormula | None:
    text = english.lower()
    best: CatalogFormula | None = None
    best_score = 0
    for item in catalog.formulas:
        score = sum(1 for alias in item.aliases if alias.lower() in text)
        if score > best_score:
            best = item
            best_score = score
    if best_score:
        return best
    shape = str(config.get("shape") or "").lower()
    constants = dict(config.get("constants") or {})
    if shape == "sequential":
        try:
            return catalog.get("running_balance")
        except KeyError:
            return None
    if config.get("threshold") is not None or ("pct" in constants and "amount" in constants):
        try:
            return catalog.get("min_pct_amount_tolerance")
        except KeyError:
            return None
    return None


_WORD_AMOUNTS = {
    "fifty": 50,
    "twenty": 20,
    "ten": 10,
    "hundred": 100,
    "thousand": 1000,
}


def fill_slots_from_english(english: str, item: CatalogFormula, existing: dict[str, Any]) -> dict[str, Any]:
    out = dict(existing)
    compact = str(english).replace(",", "")
    lower = compact.lower()
    if "pct" in item.slots and out.get("pct") in (None, ""):
        match = re.search(r"(\d+(?:\.\d+)?)\s*%", compact)
        if not match:
            match = re.search(r"(\d+(?:\.\d+)?)\s*percent", lower)
        if match:
            out["pct"] = float(match.group(1)) / 100.0
        else:
            word_pct = re.search(r"\b(one|two|half)\s+percent\b", lower)
            if word_pct:
                out["pct"] = {"one": 0.01, "two": 0.02, "half": 0.005}[word_pct.group(1)]
    if "amount" in item.slots and out.get("amount") in (None, ""):
        money = re.search(r"\$\s*(\d+(?:\.\d+)?)", compact)
        usd = re.search(r"\busd\s*(\d+(?:\.\d+)?)", lower)
        dollars = re.search(r"\b(\d+(?:\.\d+)?)\s*dollars\b", lower)
        big = re.search(r"\b(\d{2,})(?:\.\d+)?\b", compact)
        if money:
            out["amount"] = float(money.group(1))
        elif usd:
            out["amount"] = float(usd.group(1))
        elif dollars:
            out["amount"] = float(dollars.group(1))
        else:
            for word, value in _WORD_AMOUNTS.items():
                if re.search(rf"\b{word}\b", lower):
                    out["amount"] = float(value)
                    break
            if out.get("amount") in (None, "") and big:
                out["amount"] = float(big.group(1))
            elif out.get("amount") in (None, "") and item.slots.get("amount", {}).get("default") is not None:
                out["amount"] = item.slots["amount"]["default"]
    for name, spec in item.slots.items():
        if out.get(name) in (None, "") and isinstance(spec, dict) and spec.get("default") is not None:
            out[name] = spec["default"]
    return out


def _logic_from_catalog(
    item: CatalogFormula,
    config: dict[str, Any],
    *,
    constants: dict[str, Any] | None = None,
    input_map: dict[str, str] | None = None,
) -> CompiledLogic:
    return CompiledLogic(
        catalog_id=item.id,
        ast=item.ast,
        gate_ast=item.gate_ast,
        shape=config.get("shape") or item.shape,
        mode=_catalog_mode(item, config),
        output=config.get("output_column") or item.output,
        inputs=item.inputs,
        constants=dict(constants or config.get("constants") or {}),
        input_map=dict(input_map or config.get("input_map") or {}),
        group_by=list(config.get("group_by") or item.group_by or []),
    )


def _catalog_mode(item: CatalogFormula, config: dict[str, Any]) -> str:
    explicit = str(config.get("mode") or "").strip()
    if explicit in {"rule", "hybrid"}:
        return explicit
    if item.gate_ast and explicit in {"", "calculation"}:
        return item.mode or "hybrid"
    return explicit or item.mode or "calculation"


def hydrate_math_config(config: dict[str, Any]) -> dict[str, Any]:
    """Copy AST, gate, slots, and mode from the formula library onto a math node."""
    catalog = load_catalog(config.get("catalog_path"))
    english = str(config.get("formula_en") or config.get("formula") or "")
    item = None
    catalog_id = str(config.get("catalog_id") or "").strip()
    if catalog_id:
        try:
            item = catalog.get(catalog_id)
        except KeyError:
            item = None
    if item is None:
        item = _match_catalog_item(english, catalog, config)
    if item is None:
        return dict(config)
    constants = fill_slots_from_english(english, item, dict(config.get("constants") or {}))
    logic = _logic_from_catalog(item, config, constants=constants, input_map=config.get("input_map"))
    return logic_to_config(config, logic)


def _fallback_logic(catalog: FormulaCatalog, config: dict[str, Any]) -> CompiledLogic | None:
    return infer_logic_from_english(str(config.get("formula_en") or config.get("formula") or ""), catalog, config)


async def compile_logic(config: dict[str, Any], llm) -> CompiledLogic:
    catalog = load_catalog(config.get("catalog_path"))
    if config.get("ast"):
        _assert_safe(config["ast"])
        if config.get("gate_ast"):
            _assert_safe(config["gate_ast"])
        constants = dict(config.get("constants") or {})
        catalog_id = config.get("catalog_id")
        if catalog_id:
            try:
                item = catalog.get(str(catalog_id))
                constants = fill_slots_from_english(
                    str(config.get("formula_en") or ""),
                    item,
                    constants,
                )
            except KeyError:
                pass
        return CompiledLogic(
            catalog_id=config.get("catalog_id"),
            ast=config["ast"],
            gate_ast=config.get("gate_ast"),
            shape=config.get("shape") or "per_row",
            mode=config.get("mode") or "calculation",
            output=config.get("output_column") or config.get("output") or "result",
            inputs=list(config.get("inputs") or []),
            constants=constants,
            input_map=dict(config.get("input_map") or {}),
            group_by=list(config.get("group_by") or []),
        )
    catalog_id = config.get("catalog_id")
    if catalog_id:
        try:
            item = catalog.get(str(catalog_id))
        except KeyError:
            item = None
        if item:
            constants = fill_slots_from_english(
                str(config.get("formula_en") or ""),
                item,
                dict(config.get("constants") or {}),
            )
            return _logic_from_catalog(item, config, constants=constants)
    english = config.get("formula_en") or config.get("formula")
    if not english:
        raise ValueError("math node needs catalog_id, ast, or formula_en")
    inferred = infer_logic_from_english(str(english), catalog, config)
    if inferred:
        return inferred
    prompt = (
        "Pick exactly one formula from this library. Do not invent an expression.\n"
        "Return catalog_id plus any constants and input_map you can fill from the user's words.\n"
        f"{catalog_digest(config.get('catalog_path'))}\n\n"
        f"User formula: {english}\n"
        f"Existing constants: {config.get('constants') or {}}\n"
        f"Existing input_map: {config.get('input_map') or {}}"
    )
    try:
        payload = await llm.complete_json("reasoning", prompt, SELECT_SCHEMA)
    except LLMError as exc:
        logger.warning("formula pick llm failed: %s", exc)
        fallback = _fallback_logic(catalog, config)
        if fallback:
            return fallback
        raise ValueError(
            "Math could not match this formula to the library. "
            "Confirm the agent again so Math saves a catalog formula, then Save."
        ) from None
    cid = str(payload.get("catalog_id") or "").strip()
    if cid not in catalog.ids():
        fallback = _fallback_logic(catalog, config)
        if fallback:
            return fallback
        raise ValueError(
            "Math could not match this formula to the library. "
            "Confirm the agent again so Math saves a catalog formula, then Save."
        )
    item = catalog.get(cid)
    constants = fill_slots_from_english(
        str(english),
        item,
        {**dict(config.get("constants") or {}), **dict(payload.get("constants") or {})},
    )
    input_map = {**dict(config.get("input_map") or {}), **dict(payload.get("input_map") or {})}
    return _logic_from_catalog(item, config, constants=constants, input_map=input_map)


def logic_to_config(value: dict[str, Any], logic: CompiledLogic) -> dict[str, Any]:
    out = dict(value)
    if logic.catalog_id:
        out["catalog_id"] = logic.catalog_id
    out["ast"] = logic.ast
    if logic.gate_ast:
        out["gate_ast"] = logic.gate_ast
    out["shape"] = logic.shape or out.get("shape") or "per_row"
    out["mode"] = logic.mode or out.get("mode") or "calculation"
    out["output_column"] = logic.output or out.get("output_column") or "result"
    constants = {**dict(out.get("constants") or {}), **dict(logic.constants or {})}
    if constants:
        out["constants"] = constants
    if logic.input_map:
        out["input_map"] = {**dict(out.get("input_map") or {}), **logic.input_map}
    if logic.group_by and not out.get("group_by"):
        out["group_by"] = logic.group_by
    source = str(out.get("formula_en") or out.get("catalog_id") or out.get("ast") or "")
    out["compiled_from"] = source
    return out


async def compile_math_value(value: dict[str, Any], llm) -> dict[str, Any]:
    source = str(value.get("formula_en") or value.get("catalog_id") or value.get("ast") or "")
    if not source:
        return value
    if value.get("compiled_from") == source and value.get("ast"):
        return value
    synced = compile_math_value_sync(value)
    if synced.get("ast"):
        return synced
    cfg = dict(value)
    if value.get("formula_en") and value.get("compiled_from") != source:
        cfg.pop("ast", None)
        cfg.pop("gate_ast", None)
    logic = await compile_logic(cfg, llm)
    return logic_to_config(value, logic)
