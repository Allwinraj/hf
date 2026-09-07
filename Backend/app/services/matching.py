from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from typing import Any

NORMALIZE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["aliases"],
    "properties": {
        "aliases": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["raw", "canonical"],
                "properties": {
                    "raw": {"type": "string"},
                    "canonical": {"type": "string"},
                },
            },
        }
    },
}

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%Y/%m/%d",
)


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip().casefold())


def _norm_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", _norm(value))


_COLUMN_ALIASES = {
    "po": ("ponumber", "pono", "purchaseorder"),
    "ponumber": ("po", "pono"),
    "ref": ("reference", "referencenumber", "referenceno"),
    "reference": ("ref", "referencenumber"),
    "referencenumber": ("ref", "reference", "referenceno"),
    "inv": ("invoice", "invoicenumber"),
    "invoice": ("inv", "invoicenumber"),
    "invoicenumber": ("invoice", "inv"),
    "amt": ("amount",),
    "amount": ("amt",),
    "qty": ("quantity",),
    "quantity": ("qty",),
    "line": ("linenumber", "lineno"),
    "linenumber": ("line", "lineno"),
    "customername": ("payername", "customer", "name"),
    "payername": ("customername", "customer", "name"),
    "actual": ("amountreceived", "paidamount"),
    "expected": ("invoicetotal", "totalamount"),
    "totalamount": ("invoicetotal", "invoiceamount"),
    "invoicetotal": ("totalamount", "invoiceamount"),
}

_NAME_KEYS = {
    "customername",
    "payername",
    "name",
    "vendor",
    "vendorname",
    "customer",
}

_LEGAL_SUFFIX = re.compile(r"\b(incorporated|company|limited|corp|llc|ltd|inc|co)\b")
_NAME_ABBREV = {
    "whsle": "wholesale",
    "wsl": "wholesale",
    "mfg": "manufacturing",
    "mfr": "manufacturer",
    "intl": "international",
    "svc": "services",
    "svcs": "services",
}


def bind_column(row: dict[str, Any], name: str) -> str | None:
    if not name:
        return None
    if name in row:
        return name
    want = _norm_name(name)
    if not want:
        return None
    aliases = {want, *(_COLUMN_ALIASES.get(want) or ())}
    cols = list(row.keys())
    for col in cols:
        if _norm(col) == _norm(name):
            return col
    for col in cols:
        got = _norm_name(col)
        if got in aliases or want in (_COLUMN_ALIASES.get(got) or ()):
            return col
    return None


def get_bound(row: dict[str, Any], name: str) -> Any:
    col = bind_column(row, name)
    if col is None:
        return None
    return row.get(col)


def flatten_record(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict) or "sources" not in row or not isinstance(row.get("sources"), dict):
        return dict(row) if isinstance(row, dict) else {}
    out = dict(row)
    keys = row.get("keys")
    if isinstance(keys, dict):
        for key, val in keys.items():
            out.setdefault(str(key), val)
    for _sid, src in row["sources"].items():
        if not isinstance(src, dict):
            continue
        for key, val in src.items():
            out.setdefault(key, val)
    return out


def infer_keys(tables: list[SourceTable]) -> list[str]:
    if not tables:
        return []
    shared: set[str] | None = None
    for table in tables:
        cols: set[str] = set()
        for row in table.rows[:40]:
            cols.update(str(k) for k in row.keys())
        shared = cols if shared is None else shared & cols
    if not shared:
        return []
    preferred = [
        "po_number",
        "po",
        "invoice",
        "invoice_number",
        "reference",
        "reference_number",
        "line",
        "line_number",
        "amount",
    ]
    ordered = [k for k in preferred if any(_norm_name(c) == _norm_name(k) or _norm_name(c).endswith(_norm_name(k)) for c in shared)]
    bound = []
    seen = set()
    for name in ordered:
        for col in shared:
            if col in seen:
                continue
            if _norm_name(col) == _norm_name(name) or _norm_name(col).endswith(_norm_name(name)):
                bound.append(col)
                seen.add(col)
                break
    if bound:
        return bound
    skip = {_norm_name(x) for x in ("date", "posted", "cleared", "description", "memo", "narration")}
    return [c for c in sorted(shared) if _norm_name(c) not in skip][:4]


def guess_date_column(tables: list[SourceTable], keys: list[str]) -> str | None:
    key_norm = {_norm_name(k) for k in keys}
    hints = {"date", "posted", "cleared", "valuedate", "txndate", "transactiondate"}
    for table in tables:
        row = table.rows[0] if table.rows else {}
        for col in row:
            n = _norm_name(col)
            if n in key_norm:
                continue
            if n in hints or n.endswith("date"):
                return col
    return None


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    try:
        return Decimal(str(value).replace(",", "").replace("$", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _fuzzy(a: Any, b: Any) -> float:
    left, right = _norm(a), _norm(b)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return SequenceMatcher(None, left, right).ratio()


@dataclass
class SourceTable:
    source_id: str
    rows: list[dict[str, Any]]


@dataclass
class Unified:
    status: str
    confidence: float
    sources: dict[str, dict[str, Any]]
    keys: dict[str, Any] = field(default_factory=dict)
    direction: str | None = None
    allocation: list[dict[str, Any]] | None = None
    residual: dict[str, Any] | None = None
    relationship: str = "normal"
    evidence: list[dict[str, Any]] = field(default_factory=list)
    variance: dict[str, Any] | None = None
    display: dict[str, Any] = field(default_factory=dict)

    def as_row(self) -> dict[str, Any]:
        raw = {
            **dict(self.display or {}),
            "status": self.status,
            "confidence": self.confidence,
            "sources": self.sources,
            "keys": self.keys,
            "direction": self.direction,
            "allocation": self.allocation,
            "residual": self.residual,
            "relationship": self.relationship,
            "evidence": self.evidence,
            "variance": self.variance,
        }
        return flatten_record(raw)


def collect_sources(envelopes: list[Any]) -> list[SourceTable]:
    tables: list[SourceTable] = []
    for env in envelopes:
        payload = env.payload if hasattr(env, "payload") else env
        if payload.get("kind") == "knowledge":
            continue
        rows = payload.get("rows")
        if not rows:
            continue
        source_id = payload.get("file_id") or getattr(env, "node_id", None) or f"s{len(tables)}"
        tables.append(SourceTable(str(source_id), [dict(r) for r in rows]))
    return tables


def key_list(config: dict[str, Any]) -> list[str]:
    keys = config.get("keys") or config.get("match_keys") or []
    out: list[str] = []
    for item in keys:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            out.append(str(item.get("column") or item.get("name")))
    return [k for k in out if k]


async def run_match(config: dict[str, Any], tables: list[SourceTable], llm) -> list[Unified]:
    mode = (config.get("mode") or "structural").lower()
    cfg = dict(config)
    if not key_list(cfg) and len(tables) >= 2:
        cfg["keys"] = infer_keys(tables)
    if mode == "dedupe" or len(tables) == 1:
        return await _dedupe(cfg, tables[0] if tables else SourceTable("s0", []), llm)
    flags = dict(cfg.get("flags") or {})
    if mode == "semantic":
        aliases: dict[str, str] = {}
        for table in tables:
            aliases.update(await _aliases(llm, table.rows, cfg))
        cfg["_aliases"] = aliases
    if _looks_like_cash_apply(tables, cfg):
        return _cash_apply(cfg, tables)
    if flags.get("allocation") or flags.get("split"):
        return _allocate(cfg, tables)
    if flags.get("keyless"):
        return await _keyless(cfg, tables, llm)
    if mode == "semantic":
        return await _semantic(cfg, tables, llm)
    return _structural(cfg, tables)


async def _dedupe(config: dict[str, Any], table: SourceTable, llm) -> list[Unified]:
    keys = key_list(config)
    semantic = (config.get("mode") or "").lower() == "semantic"
    aliases = await _aliases(llm, table.rows, config) if semantic else {}
    clusters: dict[tuple, list[int]] = defaultdict(list)
    for i, row in enumerate(table.rows):
        if keys:
            token = tuple(_canon(get_bound(row, k), aliases) for k in keys)
        elif semantic:
            fields = config.get("fuzzy_fields") or list(row.keys())[:3]
            token = tuple(_canon(row.get(f), aliases) for f in fields)
        else:
            token = tuple(_norm(v) for v in row.values())
        clusters[token].append(i)

    results: list[Unified] = []
    for token, idxs in clusters.items():
        members = [table.rows[i] for i in idxs]
        master = dict(members[0])
        if len(members) == 1:
            results.append(
                Unified(
                    status="matched",
                    confidence=1.0,
                    sources={table.source_id: master},
                    keys=dict(zip(keys, token)) if keys else {},
                    evidence=[{"type": "dedupe", "cluster_size": 1}],
                )
            )
            continue
        results.append(
            Unified(
                status="matched",
                confidence=1.0 if not semantic else 0.9,
                sources={table.source_id: master},
                keys=dict(zip(keys, token)) if keys else {},
                evidence=[
                    {
                        "type": "dedupe_cluster",
                        "cluster_size": len(members),
                        "members": members,
                        "merge": "keep_first",
                    }
                ],
            )
        )
        results.append(
            Unified(
                status="near-match",
                confidence=0.9,
                sources={f"{table.source_id}[{n}]": m for n, m in enumerate(members)},
                relationship="normal",
                evidence=[{"type": "dedupe_audit", "cluster_size": len(members)}],
            )
        )
    return results


def _structural(config: dict[str, Any], tables: list[SourceTable]) -> list[Unified]:
    keys = key_list(config)
    window = dict(config.get("window") or {})
    window_col = window.get("column") or guess_date_column(tables, keys)
    window_days = int(window.get("days") or config.get("window_days") or 0)
    flags = dict(config.get("flags") or {})
    aliases = dict(config.get("_aliases") or {})
    exact_keys = [k for k in keys if _norm_name(k) != _norm_name(window_col or "")]
    used: list[set[int]] = [set() for _ in tables]
    results: list[Unified] = []

    if not tables:
        return results

    base = tables[0]
    for i, left in enumerate(base.rows):
        group = {base.source_id: left}
        evidence: list[dict[str, Any]] = []
        ok = True
        conf = 1.0
        for t_index, other in enumerate(tables[1:], start=1):
            found = None
            for j, right in enumerate(other.rows):
                if j in used[t_index]:
                    continue
                if flags.get("directional") and not _opposite_direction(left, right, config):
                    continue
                if flags.get("distinct_guard") and _distinct_pair(left, right, config):
                    results.append(
                        Unified(
                            status="distinct",
                            confidence=0.4,
                            sources={base.source_id: left, other.source_id: right},
                            relationship="distinct",
                            evidence=[{"type": "distinct_guard", "reason": "identity fields differ"}],
                        )
                    )
                    continue
                if not _keys_equal(left, right, exact_keys, aliases):
                    continue
                if window_col and window_days:
                    d1, d2 = _date(get_bound(left, window_col)), _date(get_bound(right, window_col))
                    if d1 and d2 and abs((d1 - d2).days) > window_days:
                        continue
                    if d1 and d2 and d1 != d2:
                        conf = min(conf, 0.9)
                        evidence.append(
                            {
                                "type": "date_window",
                                "days": abs((d1 - d2).days),
                                "allowed": window_days,
                            }
                        )
                found = j
                group[other.source_id] = right
                break
            if found is None:
                ok = False
                break
            used[t_index].add(found)
        if not ok:
            results.append(
                Unified(
                    status="unmatched",
                    confidence=0.0,
                    sources={base.source_id: left},
                    keys={k: get_bound(left, k) for k in keys},
                    evidence=[{"type": "unmatched", "source": base.source_id}],
                )
            )
            continue
        used[0].add(i)
        if flags.get("reversal") and _is_reversal(group, config):
            rel = "reversal"
        else:
            rel = "normal"
        amount_col = (config.get("flags") or {}).get("amount_column") or config.get("amount_column")
        variance = _amount_variance(group, amount_col) if amount_col else None
        direction = _direction_label(group, config) if flags.get("directional") else None
        results.append(
            Unified(
                status="matched",
                confidence=conf,
                sources=group,
                keys={k: get_bound(left, k) for k in keys},
                direction=direction,
                relationship=rel,
                evidence=evidence or [{"type": "exact" if conf == 1 else "window", "keys": keys}],
                variance=variance,
            )
        )

    for t_index, table in enumerate(tables[1:], start=1):
        for j, row in enumerate(table.rows):
            if j not in used[t_index]:
                results.append(
                    Unified(
                        status="unmatched",
                        confidence=0.0,
                        sources={table.source_id: row},
                        keys={k: get_bound(row, k) for k in keys},
                        evidence=[{"type": "unmatched", "source": table.source_id}],
                    )
                )
    return results


async def _semantic(config: dict[str, Any], tables: list[SourceTable], llm) -> list[Unified]:
    aliases: dict[str, str] = {}
    for table in tables:
        aliases.update(await _aliases(llm, table.rows, config))
    cfg = dict(config)
    cfg["_aliases"] = aliases
    cfg.setdefault("flags", {})
    results = _structural(_with_aliases(cfg, aliases), tables)
    threshold = float(config.get("confidence_threshold") or 0.85)
    fuzzy_fields = list(config.get("fuzzy_fields") or [])
    if fuzzy_fields:
        results = _rescore_fuzzy(results, tables, fuzzy_fields, aliases, threshold, config)
    for item in results:
        if item.status == "matched" and item.confidence < threshold:
            item.status = "near-match"
    return results


def _with_aliases(config: dict[str, Any], aliases: dict[str, str]) -> dict[str, Any]:
    patched = dict(config)
    patched["_aliases"] = aliases
    return patched


def _keys_equal(left: dict, right: dict, keys: list[str], aliases: dict[str, str] | None = None) -> bool:
    if not keys:
        return True
    aliases = aliases or {}
    for key in keys:
        if _norm_name(key) in _NAME_KEYS or "name" in _norm_name(key):
            left_val = _name_key(get_bound(left, key), aliases)
            right_val = _name_key(get_bound(right, key), aliases)
        else:
            left_val = _canon(get_bound(left, key), aliases)
            right_val = _canon(get_bound(right, key), aliases)
        if not left_val or left_val != right_val:
            return False
    return True


def _canon(value: Any, aliases: dict[str, str]) -> str:
    raw = _norm(value)
    return aliases.get(raw, raw)


def _name_key(value: Any, aliases: dict[str, str] | None = None) -> str:
    text = _canon(value, aliases or {})
    for src, dst in _NAME_ABBREV.items():
        text = re.sub(rf"\b{src}\b", dst, text)
    text = _LEGAL_SUFFIX.sub(" ", text)
    return re.sub(r"[^a-z0-9]+", "", text)


async def _aliases(llm, rows: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, str]:
    fields = list(config.get("normalize_fields") or config.get("fuzzy_fields") or [])
    if not fields or llm is None:
        return {}
    values = sorted({_norm(row.get(f)) for row in rows for f in fields if row.get(f)})
    if not values:
        return {}
    prompt = (
        "Normalize these entity strings to a canonical form. "
        "Keep genuinely different legal entities distinct.\n"
        f"{values}"
    )
    try:
        payload = await llm.complete_json("reconciliation", prompt, NORMALIZE_SCHEMA)
    except Exception:
        return {}
    out = {}
    for item in payload.get("aliases") or []:
        out[_norm(item.get("raw"))] = _norm(item.get("canonical"))
    return out


def _rescore_fuzzy(
    results: list[Unified],
    tables: list[SourceTable],
    fields: list[str],
    aliases: dict[str, str],
    threshold: float,
    config: dict[str, Any],
) -> list[Unified]:
    return results


def _opposite_direction(left: dict, right: dict, config: dict[str, Any]) -> bool:
    fields = dict(config.get("direction_fields") or {})
    frm, to = fields.get("from", "from_entity"), fields.get("to", "to_entity")
    return _norm(left.get(frm)) == _norm(right.get(to)) and _norm(left.get(to)) == _norm(
        right.get(frm)
    )


def _direction_label(group: dict[str, dict], config: dict[str, Any]) -> str | None:
    fields = dict(config.get("direction_fields") or {})
    frm, to = fields.get("from", "from_entity"), fields.get("to", "to_entity")
    first = next(iter(group.values()), {})
    if first.get(frm) and first.get(to):
        return f"{first.get(frm)} → {first.get(to)}"
    return None


def _distinct_pair(left: dict, right: dict, config: dict[str, Any]) -> bool:
    fields = list(config.get("identity_fields") or ["name"])
    guard = list(config.get("distinct_fields") or ["tax_id"])
    similar = all(_fuzzy(left.get(f), right.get(f)) >= 0.8 for f in fields if left.get(f) or right.get(f))
    differ = any(
        _norm(left.get(f)) and _norm(right.get(f)) and _norm(left.get(f)) != _norm(right.get(f))
        for f in guard
    )
    return similar and differ


def _is_reversal(group: dict[str, dict], config: dict[str, Any]) -> bool:
    col = config.get("amount_column") or "amount"
    amounts = [_dec(get_bound(row, col)) for row in group.values()]
    amounts = [a for a in amounts if a is not None]
    return any(a < 0 for a in amounts)


def _amount_variance(group: dict[str, dict], column: str | None) -> dict[str, Any] | None:
    if not column:
        return None
    amounts = [_dec(get_bound(row, column)) for row in group.values()]
    amounts = [a for a in amounts if a is not None]
    if len(amounts) < 2:
        return None
    delta = amounts[0] - amounts[1]
    return {"column": column, "delta": str(delta)}


def _table_colset(table: SourceTable) -> set[str]:
    row = table.rows[0] if table.rows else {}
    return {_norm_name(k) for k in row}


def _looks_like_register_table(table: SourceTable) -> bool:
    cols = _table_colset(table)
    has_id = bool(cols & {"invoicenumber", "invoiceno", "billnumber", "documentnumber"})
    has_total = bool(cols & {"invoicetotal", "totalamount", "invoiceamount"})
    has_party = bool(cols & {"customername", "customer", "vendorname", "vendor", "name"})
    return (has_id or has_total) and has_party


def _looks_like_statement_table(table: SourceTable) -> bool:
    cols = _table_colset(table)
    return bool(cols & {"payername", "banktxnid", "debitcredit", "statementdate", "valuedate"})


def _looks_like_cash_apply(tables: list[SourceTable], config: dict[str, Any]) -> bool:
    if len(tables) < 2:
        return False
    flags = dict(config.get("flags") or {})
    if flags.get("group_receipts"):
        return True
    keys = key_list(config)
    name_keys = [k for k in keys if _norm_name(k) in _NAME_KEYS or "name" in _norm_name(k)]
    if not name_keys and str(config.get("mode") or "").lower() != "semantic":
        return False
    has_register = any(_looks_like_register_table(t) for t in tables)
    has_statement = any(_looks_like_statement_table(t) for t in tables)
    return has_register and has_statement


def _is_receipt(row: dict[str, Any]) -> bool:
    dc = _norm(get_bound(row, "debit_credit") or row.get("Debit Credit"))
    if dc in {"dr", "debit", "d"}:
        return False
    if dc in {"cr", "credit", "c"}:
        return True
    ttype = _norm(get_bound(row, "txn_type") or row.get("Txn Type"))
    if ttype in {"withdrawal", "fee", "sweep"}:
        return False
    amt = _dec(get_bound(row, "amount"))
    return amt is None or amt >= 0


def _as_of_date(tables: list[SourceTable]) -> date:
    latest: date | None = None
    for table in tables:
        for row in table.rows:
            for col in ("statement_date", "value_date", "invoice_date", "due_date"):
                got = _date(get_bound(row, col))
                if got and (latest is None or got > latest):
                    latest = got
    return latest or date.today()


def _cash_apply(config: dict[str, Any], tables: list[SourceTable]) -> list[Unified]:
    invoices = next((t for t in tables if _looks_like_register_table(t)), None)
    bank = next((t for t in tables if _looks_like_statement_table(t)), None)
    if not invoices or not bank:
        return _structural(config, tables)
    keys = key_list(config) or ["customer_name"]
    aliases = dict(config.get("_aliases") or {})
    as_of = _as_of_date(tables)
    receipts = [(j, dict(row)) for j, row in enumerate(bank.rows) if _is_receipt(row)]
    used: set[int] = set()
    results: list[Unified] = []

    for invoice in invoices.rows:
        paired: list[tuple[int, dict[str, Any]]] = []
        for j, rec in receipts:
            if j in used:
                continue
            if _keys_equal(invoice, rec, keys, aliases):
                paired.append((j, rec))
        expected = (
            _dec(get_bound(invoice, "invoice_total"))
            or _dec(get_bound(invoice, "total_amount"))
            or _dec(get_bound(invoice, "invoice_amount"))
            or Decimal("0")
        )
        paid = sum((_dec(get_bound(rec, "amount")) or Decimal("0")) for _, rec in paired)
        due = _date(get_bound(invoice, "due_date"))
        days_past = (as_of - due).days if due else None
        payers = []
        refs = []
        alloc = []
        for j, rec in paired:
            used.add(j)
            payer = get_bound(rec, "payer_name")
            if payer and payer not in payers:
                payers.append(payer)
            ref = get_bound(rec, "reference_number") or get_bound(rec, "bank_txn_id")
            if ref:
                refs.append(str(ref))
            alloc.append(
                {
                    "bank_txn_id": get_bound(rec, "bank_txn_id"),
                    "applied": str(_dec(get_bound(rec, "amount")) or 0),
                }
            )
        if not paired:
            outcome = "unpaid"
            status = "unmatched"
            conf = 0.0
            residual = None
        else:
            status = "matched"
            conf = 1.0
            residual = {"amount": str(paid - expected), "reason": "variance"} if paid != expected else None
            if len(paired) >= 2 and paid >= expected * Decimal("1.8"):
                outcome = "duplicate"
            elif len(paired) >= 2:
                outcome = "split"
            elif paid > expected:
                outcome = "overpaid"
            elif paid < expected:
                outcome = "short"
            else:
                outcome = "paid"
        sources = {invoices.source_id: dict(invoice)}
        for j, rec in paired:
            sources[f"{bank.source_id}:{j}"] = rec
        display = {
            "invoice_number": get_bound(invoice, "invoice_number"),
            "customer_name": get_bound(invoice, "customer_name"),
            "payer_name_on_bank": ", ".join(str(p) for p in payers) if payers else None,
            "invoice_total": float(expected),
            "amount_received": float(paid) if paired else 0.0,
            "amount_difference": float(paid - expected) if paired else None,
            "payment_count": len(paired),
            "bank_references": ", ".join(refs),
            "due_date": get_bound(invoice, "due_date"),
            "invoice_status": get_bound(invoice, "status"),
            "days_past_due": days_past,
            "payment_outcome": outcome,
        }
        results.append(
            Unified(
                status=status,
                confidence=conf,
                sources=sources,
                keys={k: get_bound(invoice, k) for k in keys},
                allocation=alloc or None,
                residual=residual,
                evidence=[{"type": "cash_apply", "payments": len(paired)}],
                display=display,
            )
        )

    for j, rec in receipts:
        if j in used:
            continue
        results.append(
            Unified(
                status="unmatched",
                confidence=0.0,
                sources={bank.source_id: rec},
                evidence=[{"type": "operating_noise"}],
                display={
                    "payer_name_on_bank": get_bound(rec, "payer_name"),
                    "amount_received": get_bound(rec, "amount"),
                    "bank_references": get_bound(rec, "reference_number") or get_bound(rec, "bank_txn_id"),
                    "payment_outcome": "operating_noise",
                    "description": get_bound(rec, "description") or rec.get("description"),
                },
            )
        )
    return results


def _allocate(config: dict[str, Any], tables: list[SourceTable]) -> list[Unified]:
    if len(tables) < 2:
        return []
    left, right = tables[0], tables[1]
    amount_col = config.get("amount_column") or "amount"
    keys = key_list(config)
    results: list[Unified] = []
    remaining_right = [
        {"row": dict(r), "left": _dec(r.get(amount_col)) or Decimal("0"), "idx": i}
        for i, r in enumerate(right.rows)
    ]
    used_right: set[int] = set()
    for pay in left.rows:
        pool = _dec(pay.get(amount_col)) or Decimal("0")
        original = pool
        alloc: list[dict[str, Any]] = []
        for item in remaining_right:
            if item["left"] <= 0:
                continue
            if keys and not _keys_equal(pay, item["row"], keys):
                continue
            take = min(pool, item["left"])
            if take <= 0:
                continue
            item["left"] -= take
            pool -= take
            used_right.add(item["idx"])
            alloc.append(
                {
                    "target": item["row"],
                    "applied": str(take),
                    "open": str(item["left"]),
                }
            )
            if pool <= 0:
                break
        conf = 1.0 if pool == 0 and alloc else 0.8 if alloc else 0.0
        residual = {"amount": str(pool), "reason": "unapplied"} if pool > 0 else None
        if alloc:
            results.append(
                Unified(
                    status="matched",
                    confidence=conf,
                    sources={left.source_id: pay, right.source_id: alloc[0]["target"]},
                    keys={k: pay.get(k) for k in keys},
                    allocation=alloc,
                    residual=residual,
                    evidence=[{"type": "allocation", "applied": str(original - pool)}],
                )
            )
        elif pool > 0:
            results.append(
                Unified(
                    status="unmatched",
                    confidence=0.0,
                    sources={left.source_id: pay},
                    residual=residual,
                    evidence=[{"type": "unmatched_payment"}],
                )
            )
    for item in remaining_right:
        if item["idx"] not in used_right:
            results.append(
                Unified(
                    status="unmatched",
                    confidence=0.0,
                    sources={right.source_id: item["row"]},
                    residual={"amount": str(item["left"]), "reason": "unpaid"}
                    if item["left"]
                    else None,
                    evidence=[{"type": "unmatched_invoice"}],
                )
            )
    return results


async def _keyless(config: dict[str, Any], tables: list[SourceTable], llm) -> list[Unified]:
    if len(tables) < 2:
        return []
    fields = list(config.get("identity_fields") or ["name", "address", "tax_id"])
    aliases = await _aliases(llm, tables[0].rows + tables[1].rows, {**config, "fuzzy_fields": fields})
    threshold = float(config.get("confidence_threshold") or 0.85)
    used: set[int] = set()
    results: list[Unified] = []
    for left in tables[0].rows:
        best_j = None
        best = 0.0
        for j, right in enumerate(tables[1].rows):
            if j in used:
                continue
            if (config.get("flags") or {}).get("distinct_guard") and _distinct_pair(left, right, config):
                results.append(
                    Unified(
                        status="distinct",
                        confidence=0.35,
                        sources={tables[0].source_id: left, tables[1].source_id: right},
                        relationship="distinct",
                        evidence=[{"type": "distinct_guard", "fields": fields}],
                    )
                )
                used.add(j)
                continue
            scores = [_fuzzy(_canon(left.get(f), aliases), _canon(right.get(f), aliases)) for f in fields]
            score = sum(scores) / len(scores) if scores else 0.0
            if score > best:
                best, best_j = score, j
        if best_j is not None and best >= 0.5:
            used.add(best_j)
            status = "matched" if best >= threshold else "near-match"
            results.append(
                Unified(
                    status=status,
                    confidence=round(best, 4),
                    sources={tables[0].source_id: left, tables[1].source_id: tables[1].rows[best_j]},
                    evidence=[{"type": "identity", "fields": fields, "score": best}],
                )
            )
        else:
            results.append(
                Unified(
                    status="unmatched",
                    confidence=0.0,
                    sources={tables[0].source_id: left},
                    evidence=[{"type": "keyless_unmatched"}],
                )
            )
    return results


def split_ports(records: list[Unified]) -> dict[str, list[dict[str, Any]]]:
    matched, residuals, exceptions = [], [], []
    for rec in records:
        row = rec.as_row()
        if rec.status == "matched" and rec.residual and rec.allocation:
            matched.append(row)
            residuals.append(row)
        elif rec.status == "matched":
            matched.append(row)
        elif rec.residual and rec.status != "distinct":
            residuals.append(row)
        else:
            exceptions.append(row)
    return {"matched": matched, "residuals": residuals, "exceptions": exceptions}
