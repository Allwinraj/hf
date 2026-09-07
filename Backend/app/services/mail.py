from __future__ import annotations

import asyncio
import email
import imaplib
import io
import json
import re
import smtplib
import ssl
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from typing import Any

from pypdf import PdfReader

from app.core.llm import LLMError
from app.services.mailbox_defaults import mailbox_config

PR_SUBJECT_RE = re.compile(
    r"\bpr\b|pr request|purchase request|purchase requisition|purchase order|"
    r"\bpo\b request|po request|procurement",
    re.IGNORECASE,
)

_WORD_NUMS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


@dataclass
class MailMessage:
    uid: str
    subject: str
    from_addr: str
    date: str
    body: str
    pdf_name: str = ""
    pdf_text: str = ""
    kept: bool = False
    skip_reason: str = ""
    raw_flags: str = ""


def is_pr_subject(subject: str) -> bool:
    return bool(PR_SUBJECT_RE.search(subject or ""))


def decode_header_value(value: object) -> str:
    if value is None:
        return ""
    try:
        return str(make_header(decode_header(str(value)))).strip()
    except Exception:  # noqa: BLE001
        return str(value).strip()


def pdf_text_from_bytes(blob: bytes) -> str:
    if not blob:
        return ""
    try:
        reader = PdfReader(io.BytesIO(blob))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages).strip()
    except Exception:  # noqa: BLE001
        return ""


def parse_rfc822(blob: bytes, uid: str = "sample") -> MailMessage:
    msg = email.message_from_bytes(blob)
    body = ""
    html = ""
    pdf_name = ""
    pdf_text = ""
    for part in msg.walk():
        ctype = part.get_content_type()
        disp = str(part.get("Content-Disposition") or "")
        name = part.get_filename() or ""
        payload = part.get_payload(decode=True) or b""
        if ctype == "text/plain" and "attachment" not in disp.lower() and not body:
            charset = part.get_content_charset() or "utf-8"
            body = payload.decode(charset, errors="replace")
        elif ctype == "text/html" and "attachment" not in disp.lower() and not html:
            charset = part.get_content_charset() or "utf-8"
            html = payload.decode(charset, errors="replace")
        elif ctype == "application/pdf" or name.lower().endswith(".pdf"):
            pdf_name = decode_header_value(name) or "attachment.pdf"
            pdf_text = pdf_text_from_bytes(payload)
    if not body and html:
        body = re.sub(r"<[^>]+>", " ", html)
        body = re.sub(r"\s+", " ", body).strip()
    date_raw = msg.get("Date")
    try:
        date = parsedate_to_datetime(date_raw).isoformat() if date_raw else ""
    except Exception:  # noqa: BLE001
        date = decode_header_value(date_raw)
    subject = decode_header_value(msg.get("Subject"))
    return MailMessage(
        uid=uid,
        subject=subject,
        from_addr=decode_header_value(msg.get("From")),
        date=date,
        body=body.strip(),
        pdf_name=pdf_name,
        pdf_text=pdf_text,
        kept=is_pr_subject(subject),
        skip_reason="" if is_pr_subject(subject) else "subject_not_pr",
    )


def extract_pr(message: MailMessage) -> dict[str, Any]:
    blob = f"{message.subject}\n{message.body}\n{message.pdf_text}"
    qty = _find_qty(blob)
    budget = _find_budget(blob)
    location = _find_location(message.subject, blob)
    item = _find_item(message.subject, blob)
    return {
        "mail_id": message.uid,
        "subject": message.subject,
        "from": message.from_addr,
        "date": message.date,
        "qty": qty,
        "item": item,
        "location": location,
        "needed_by": _find_needed_by(blob),
        "cost_centre": _find_cost_centre(blob),
        "budget": budget,
        "spec_ref": _find_spec_ref(blob) or message.pdf_name,
        "pdf_name": message.pdf_name,
        "specs": {
            "cpu": _find_spec(blob, r"(Intel Core i[0-9][^\n.]*)"),
            "ram": _find_spec(blob, r"(Minimum\s+\d+\s*GB RAM|\d+\s*GB RAM)"),
            "ssd": _find_spec(blob, r"(Minimum\s+\d+\s*GB SSD|\d+\s*GB SSD)"),
            "warranty": _find_spec(blob, r"(Minimum [^\n]*warranty|[^\n]*three-year[^\n]*warranty)"),
        },
        "catalogue_required": bool(re.search(r"catalogue|catalog item", blob, re.I)),
        "approved_supplier_required": bool(re.search(r"approved[^\n]{0,40}supplier", blob, re.I)),
        "substitution_allowed": not bool(re.search(r"no product substitution|no substitution", blob, re.I)),
        "body": message.body[:4000],
        "pdf_text": message.pdf_text[:8000],
        "send_status": "draft",
    }


def flatten_mail_row(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    mail_id = item.get("mail_id") or source.get("mail_id")
    if not mail_id:
        return item
    merged = dict(source)
    for key, value in item.items():
        if key == "source":
            continue
        if value is not None:
            merged[key] = value
    merged["mail_id"] = str(mail_id)
    if source:
        merged["source"] = source
    return merged


def _decision_label(verdict: str) -> str:
    if verdict == "approved":
        return "Approved"
    if verdict == "escalated":
        return "Escalated — not approved"
    return "Flagged — not approved"


def _money(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        number = float(value)
        if number == int(number):
            return f"Rs. {int(number):,}"
        return f"Rs. {number:,.2f}"
    except (TypeError, ValueError):
        text = str(value).strip()
        if re.match(r"(?i)^rs\.?\s*", text):
            return text
        return f"Rs. {text}"


def _route_target(*texts: str) -> str:
    blob = " ".join(t for t in texts if t)
    match = re.search(r"route(?:d)? to ([^.;\n]+)", blob, re.I)
    if not match:
        return ""
    return match.group(1).strip().rstrip(".")


def _looks_internal(text: str) -> bool:
    if not text or text.lower() in {"none", "n/a", "na", "-", "nil"}:
        return True
    return bool(
        re.search(
            r"dashboard|click send|smtp|human send|reviewer must|open why this result",
            text,
            re.I,
        )
    )


def _looks_procurement_task(text: str) -> bool:
    return bool(
        re.search(
            r"\b(create|raise|prepare)\b.{0,40}\b(draft )?pr\b|"
            r"\bwe will\b|"
            r"ask the requester|"
            r"procurement will",
            text,
            re.I,
        )
    )


def _to_requester(text: str) -> str:
    cleaned = re.sub(r"(?i)^ask the requester to\s+", "Please ", text.strip())
    cleaned = re.sub(r"(?i)^request the requester to\s+", "Please ", cleaned)
    cleaned = re.sub(r"(?i)^the requester should\s+", "Please ", cleaned)
    cleaned = re.sub(r"(?i)\bthe requester\b", "you", cleaned)
    cleaned = re.sub(
        r"(?i)\bthen re-run policy checks\.?",
        "then reply to this email so we can check the request again.",
        cleaned,
    )
    if cleaned and not cleaned[0].isupper():
        cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned


def _please(action: str) -> str:
    text = action.strip()
    if not text:
        return text
    if re.search(r"(?i)^please\b", text):
        return text
    return "Please " + text[0].lower() + text[1:]


def _requester_next_step(verdict: str, why: str, remediation: str) -> str:
    route = _route_target(why, remediation)
    route_line = f" It will be routed to {route}." if route else " It will be routed as the purchase policy requires."
    if verdict == "approved":
        if remediation and not _looks_internal(remediation) and not _looks_procurement_task(remediation):
            return _to_requester(remediation)
        return (
            "You do not need to raise another request or send extra documents unless the details change. "
            "We will prepare the draft purchase requisition after validation."
            + route_line
            + " If quantity, location, or coding on this request changes, reply to this email with the update."
        )
    if verdict == "escalated":
        if remediation and not _looks_internal(remediation) and not _looks_procurement_task(remediation):
            return (
                f"{_please(_to_requester(remediation))} This request is not approved yet. "
                "Reply to this email with the required approval. "
                "Do not treat this as clearance to buy until you receive an approved reply."
            )
        who = route or "the higher authority named in the purchase policy"
        return (
            f"Please obtain approval from {who} and reply to this email with that confirmation. "
            "This request is not approved yet. Do not place an order until you receive an approved reply."
        )
    if remediation and not _looks_internal(remediation) and not _looks_procurement_task(remediation):
        return (
            f"{_please(_to_requester(remediation))} This request is not approved. "
            "Reply to this email with the missing or corrected information so we can check it again."
        )
    if remediation and re.search(r"(?i)ask the requester", remediation):
        return (
            f"{_please(_to_requester(remediation))} This request is not approved. "
            "Do not treat it as clearance to buy until you receive an approved reply."
        )
    missing = why or "the missing information required by the purchase policy."
    if missing and not missing.endswith((".", "!", "?")):
        missing += "."
    return (
        f"Please reply to this email with what is still required. {missing} "
        "This request is not approved. Do not treat it as clearance to buy until you receive an approved reply."
    )


def _draft_reply_body(item: dict[str, Any], send_details: str = "") -> str:
    verdict = str(item.get("verdict") or "flagged").strip().lower()
    if verdict in {"approve", "ok"}:
        verdict = "approved"
    if verdict in {"flag", "review", "flagged_for_review"}:
        verdict = "flagged"
    if verdict in {"escalate"}:
        verdict = "escalated"
    name = send_details.strip() or "Nexus Procurement"
    qty = item.get("qty")
    goods = str(item.get("item") or "the requested items").strip()
    loc = str(item.get("location") or "").strip()
    value = _money(item.get("budget"))
    why = str(item.get("explanation") or item.get("_decision_explanation") or "").strip()
    remediation = str(item.get("remediation") or "").strip()
    qty_bit = f"{qty} " if qty not in (None, "") else ""
    request_lines = [f"Item: {qty_bit}{goods}".strip()]
    if loc:
        request_lines.append(f"Location: {loc}")
    if value:
        request_lines.append(f"Value: {value}")
    if verdict == "approved":
        outcome = "This purchase request is approved under the purchase policy."
    elif verdict == "escalated":
        outcome = "This purchase request is escalated. It is not approved."
    else:
        outcome = "This purchase request is flagged. It is not approved."
    if not why:
        why = (
            "A complete policy explanation was not stored for this request. "
            "Treat the decision line above as the result until a reviewer confirms otherwise."
        )
    next_step = _requester_next_step(verdict, why, remediation)
    return (
        "Hello,\n\n"
        "Thank you for your purchase request.\n\n"
        f"Decision: {_decision_label(verdict)}\n"
        f"{outcome}\n\n"
        "This request\n"
        + "\n".join(request_lines)
        + "\n\n"
        "Why this result\n"
        f"{why}\n\n"
        "What you need to do\n"
        f"{next_step}\n\n"
        "If you have questions, reply to this email.\n\n"
        f"Regards,\n{name}"
    )


def attach_drafts(rows: list[dict[str, Any]], send_details: str = "") -> list[dict[str, Any]]:
    out = []
    for row in rows:
        item = flatten_mail_row(row)
        if not item.get("mail_id"):
            out.append(item)
            continue
        item["send_status"] = item.get("send_status") or "draft"
        item["draft_subject"] = item.get("draft_subject") or f"Re: {item.get('subject') or 'PR Request'}"
        item["draft_body"] = _draft_reply_body(item, send_details)
        item["to_address"] = item.get("to_address") or _email_from_from(str(item.get("from") or ""))
        out.append(item)
    return out


DRAFT_MAIL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["draft_subject", "draft_body"],
    "properties": {
        "draft_subject": {"type": "string"},
        "draft_body": {"type": "string"},
    },
}


def _compact_mail_record(item: dict[str, Any]) -> dict[str, Any]:
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
        "confidence",
    )
    out = {key: item.get(key) for key in keep if item.get(key) not in (None, "")}
    excerpt = str(item.get("pdf_text") or "")[:1200].strip()
    if excerpt:
        out["attachment_excerpt"] = excerpt
    return out


def _draft_looks_complete(body: str) -> bool:
    text = (body or "").strip().lower()
    if len(text) < 80:
        return False
    if "decision" not in text:
        return False
    if "what you need to do" not in text and "what you need to do:" not in text:
        return False
    return True


async def _one_llm_draft(llm: Any, item: dict[str, Any], send_details: str) -> dict[str, Any]:
    fallback = attach_drafts([item], send_details)[0]
    if llm is None:
        return fallback
    name = send_details.strip() or str(item.get("send_details") or "Nexus Procurement")
    prompt = (
        "Write a professional reply email to the person who sent this purchase request.\n"
        "Use only the decision and fields given. Do not invent amounts, items, locations, or policy rules.\n"
        "The reader is the requester. Never mention a dashboard, SMTP, reviewers clicking Send, or internal tools.\n"
        "draft_subject should start with Re: and the original subject if present.\n"
        "draft_body must be a complete, sendable email with these sections in order, separated by blank lines:\n"
        "1) Greeting and one-line thanks.\n"
        "2) A line starting with 'Decision:' using Approved, Flagged — not approved, or Escalated — not approved, "
        "then one sentence stating the outcome clearly.\n"
        "3) A heading 'This request' then item, quantity, location, and value when present.\n"
        "4) A heading 'Why this result' then the policy explanation in clear sentences.\n"
        "5) A heading 'What you need to do' then second-person instructions for the requester only "
        "(what they must reply with, wait for, or obtain). If approved, tell them they do not need to resubmit.\n"
        "6) Invite them to reply to this email with questions.\n"
        f"7) Sign off as {name}.\n\n"
        f"Record JSON:\n{json.dumps(_compact_mail_record(item), default=str)}"
    )
    try:
        raw = await llm.complete_json("general", prompt, DRAFT_MAIL_SCHEMA, 0.2)
    except (LLMError, Exception):  # noqa: BLE001
        return fallback
    body = str((raw or {}).get("draft_body") or "").strip()
    subject = str((raw or {}).get("draft_subject") or "").strip()
    if not _draft_looks_complete(body):
        return fallback
    out = dict(fallback)
    out["draft_body"] = body
    out["draft_subject"] = subject or out.get("draft_subject")
    return out


async def attach_drafts_llm(
    rows: list[dict[str, Any]],
    llm: Any,
    send_details: str = "",
) -> list[dict[str, Any]]:
    async def one(row: dict[str, Any]) -> dict[str, Any]:
        item = flatten_mail_row(row)
        if not item.get("mail_id"):
            return item
        details = send_details or str(item.get("send_details") or "")
        return await _one_llm_draft(llm, item, details)

    return list(await asyncio.gather(*[one(row) for row in rows]))


def fetch_unseen(config: dict[str, Any] | None = None) -> list[MailMessage]:
    cfg = mailbox_config(config)
    if cfg.get("fixture_messages"):
        messages = []
        for i, raw in enumerate(cfg["fixture_messages"]):
            if isinstance(raw, dict):
                msg = MailMessage(
                    uid=str(raw.get("uid") or i + 1),
                    subject=str(raw.get("subject") or ""),
                    from_addr=str(raw.get("from") or ""),
                    date=str(raw.get("date") or ""),
                    body=str(raw.get("body") or ""),
                    pdf_name=str(raw.get("pdf_name") or ""),
                    pdf_text=str(raw.get("pdf_text") or ""),
                )
                msg.kept = is_pr_subject(msg.subject)
                msg.skip_reason = "" if msg.kept else "subject_not_pr"
                messages.append(msg)
            else:
                messages.append(parse_rfc822(bytes(raw), uid=str(i + 1)))
        return messages
    ctx = ssl.create_default_context()
    client = imaplib.IMAP4_SSL(str(cfg["imap_host"]), int(cfg["imap_port"]), ssl_context=ctx)
    client.login(str(cfg["username"]), str(cfg["password"]))
    try:
        folder = str(cfg.get("folder") or "INBOX")
        typ, _ = client.select(folder, readonly=False)
        if typ != "OK":
            raise RuntimeError(f"could not select folder {folder}")
        typ, data = client.uid("SEARCH", None, "UNSEEN")
        if typ != "OK" or not data or not data[0]:
            return []
        uids = data[0].split()
        messages: list[MailMessage] = []
        for uid in uids:
            typ, fetched = client.uid("FETCH", uid, "(FLAGS RFC822)")
            if typ != "OK" or not fetched:
                continue
            flags = ""
            blob = b""
            for item in fetched:
                if not isinstance(item, tuple):
                    continue
                flags = str(item[0])
                blob = item[1] if isinstance(item[1], (bytes, bytearray)) else b""
            parsed = parse_rfc822(bytes(blob), uid=uid.decode() if isinstance(uid, bytes) else str(uid))
            parsed.raw_flags = flags
            messages.append(parsed)
        return messages
    finally:
        try:
            client.logout()
        except Exception:  # noqa: BLE001
            pass


def mark_seen(config: dict[str, Any] | None, uids: list[str]) -> None:
    if not uids:
        return
    cfg = mailbox_config(config)
    if cfg.get("fixture_messages") is not None:
        return
    ctx = ssl.create_default_context()
    client = imaplib.IMAP4_SSL(str(cfg["imap_host"]), int(cfg["imap_port"]), ssl_context=ctx)
    client.login(str(cfg["username"]), str(cfg["password"]))
    try:
        client.select(str(cfg.get("folder") or "INBOX"), readonly=False)
        for uid in uids:
            client.uid("STORE", uid, "+FLAGS", "(\\Seen)")
    finally:
        try:
            client.logout()
        except Exception:  # noqa: BLE001
            pass


def send_smtp(config: dict[str, Any] | None, *, to_addr: str, subject: str, body: str) -> None:
    cfg = mailbox_config(config)
    if cfg.get("skip_smtp"):
        return
    msg = EmailMessage()
    from_addr = str(cfg.get("from_address") or cfg["username"])
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(str(cfg["smtp_host"]), int(cfg["smtp_port"]), timeout=30) as smtp:
        if cfg.get("smtp_starttls", True):
            smtp.starttls(context=ssl.create_default_context())
        smtp.login(str(cfg["username"]), str(cfg["password"]))
        smtp.send_message(msg)


def mailbox_preview_from_parsed(message: MailMessage) -> dict[str, Any]:
    extracted = extract_pr(message)
    return {
        "subject": message.subject,
        "from": message.from_addr,
        "body_excerpt": message.body[:1200],
        "pdf_name": message.pdf_name,
        "pdf_excerpt": message.pdf_text[:1800],
        "extracted": {
            k: extracted[k]
            for k in (
                "qty",
                "item",
                "location",
                "needed_by",
                "cost_centre",
                "budget",
                "spec_ref",
                "specs",
            )
        },
    }


def _email_from_from(value: str) -> str:
    match = re.search(r"<([^>]+)>", value)
    if match:
        return match.group(1).strip()
    return value.strip()


def _find_qty(text: str) -> int | None:
    match = re.search(r"\bQuantity\s+(\d+)\b", text, re.I)
    if match:
        return int(match.group(1))
    match = re.search(
        r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\s+[A-Za-z]",
        text,
        re.I,
    )
    if match:
        return _WORD_NUMS.get(match.group(1).lower())
    match = re.search(r"\b(\d+)\s+[A-Za-z][A-Za-z-]{2,}\b", text)
    if match:
        return int(match.group(1))
    return None


def _find_budget(text: str) -> int | None:
    match = re.search(r"(?:Rs\.?|₹)\s*([0-9,]+)", text)
    if match:
        return int(match.group(1).replace(",", ""))
    match = re.search(r"must not exceed\s*(?:Rs\.?|₹)?\s*([0-9,]+)", text, re.I)
    if match:
        return int(match.group(1).replace(",", ""))
    return None


def _find_location(subject: str, text: str) -> str:
    if "|" in (subject or ""):
        tail = subject.split("|")[-1].strip()
        if tail:
            return tail
    match = re.search(
        r"(?:joining our|Delivery location|Delivery point|office in)\s+([^\n.|]+)",
        text,
        re.I,
    )
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip(" -")
    return ""


def _find_item(subject: str, text: str) -> str:
    match = re.search(r"(?:PR Request|Purchase Request|Purchase Order)\s*[-:]\s*([^|]+)", subject or "", re.I)
    if match:
        return match.group(1).strip()
    match = re.search(
        r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+([A-Za-z][A-Za-z -]{2,40}?)\b",
        text,
        re.I,
    )
    if match:
        return match.group(1).strip()
    return (subject or "purchase request").strip()


def _find_needed_by(text: str) -> str:
    match = re.search(r"(?:needed by|required by|on or before)\s+([0-9]{1,2}\s+\w+\s+20[0-9]{2})", text, re.I)
    return match.group(1) if match else ""


def _find_cost_centre(text: str) -> str:
    match = re.search(r"\b(CC[- ]?\d+)\b", text, re.I)
    return match.group(1).replace(" ", "").upper() if match else ""


def _find_spec_ref(text: str) -> str:
    match = re.search(r"Document reference\s+([A-Z0-9][A-Z0-9._-]{4,})", text, re.I)
    if match:
        return match.group(1).strip()
    match = re.search(r"\b([A-Z]{2,5}-[A-Z0-9]{2,}-[A-Z0-9-]{4,})\b", text)
    return match.group(1) if match else ""


def _find_spec(text: str, pattern: str) -> str:
    match = re.search(pattern, text, re.I)
    return match.group(1).strip() if match else ""


def collect_mail_rows(run: Any) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    unread = 0
    skipped_noise = 0
    extra = dict(getattr(run, "extra", None) or {})
    actions = dict(extra.get("mail_actions") or {})
    for saved in extra.get("mail_rows") or []:
        if not isinstance(saved, dict) or not saved.get("mail_id"):
            continue
        by_id[str(saved["mail_id"])] = dict(saved)
    for step in getattr(run, "steps", []) or []:
        for env in getattr(step, "outputs", []) or []:
            payload = env.payload or {}
            unread = max(unread, int(payload.get("unread_fetched") or 0))
            skipped_noise = max(skipped_noise, int(payload.get("skipped_noise") or 0))
            for row in payload.get("rows") or []:
                if not isinstance(row, dict):
                    continue
                item = flatten_mail_row(row)
                if not item.get("mail_id"):
                    continue
                mid = str(item["mail_id"])
                if mid in by_id:
                    merged = dict(by_id[mid])
                    merged.update(item)
                    by_id[mid] = merged
                else:
                    by_id[mid] = item
    drafts = dict(extra.get("mail_drafts") or {})
    rows = []
    for mail_id, row in by_id.items():
        item = dict(row)
        status = str(actions.get(mail_id) or item.get("send_status") or "draft")
        if mail_id not in drafts and status == "draft" and (item.get("verdict") or item.get("explanation")):
            body = str(item.get("draft_body") or "")
            stale = (
                not body
                or "cannot auto-approve" in body.lower()
                or "dashboard" in body.lower()
                or not _draft_looks_complete(body)
            )
            if stale:
                item = attach_drafts([item])[0]
        patch = drafts.get(mail_id) or {}
        if isinstance(patch, dict):
            item.update({k: v for k, v in patch.items() if v is not None})
        if mail_id in actions:
            item["send_status"] = actions[mail_id]
        rows.append(item)
    run.extra = extra
    extra["mail_unread_fetched"] = extra.get("mail_unread_fetched") or unread
    extra["mail_skipped_noise"] = extra.get("mail_skipped_noise") or skipped_noise
    return rows


def mail_kpis(run: Any) -> dict[str, int]:
    rows = collect_mail_rows(run)
    extra = dict(getattr(run, "extra", None) or {})
    waiting = sum(1 for r in rows if str(r.get("send_status") or "draft") == "draft")
    sent = sum(1 for r in rows if str(r.get("send_status")) == "sent")
    skipped = sum(1 for r in rows if str(r.get("send_status")) == "skipped")
    return {
        "unread_fetched": int(extra.get("mail_unread_fetched") or len(rows)),
        "kept": len(rows),
        "skipped_noise": int(extra.get("mail_skipped_noise") or 0),
        "waiting": waiting,
        "sent": sent,
        "skipped_by_human": skipped,
    }


def mailbox_node_config(pipeline: Any) -> dict[str, Any]:
    for node in getattr(pipeline, "nodes", []) or []:
        cfg = dict(node.config or {})
        if node.agent == "ingestion" and (node.mode == "mailbox" or cfg.get("mode") == "mailbox"):
            return mailbox_config(cfg)
    return mailbox_config()


def save_mail_draft(
    run: Any,
    mail_id: str,
    *,
    to_address: str | None = None,
    draft_subject: str | None = None,
    draft_body: str | None = None,
) -> dict[str, Any]:
    rows = collect_mail_rows(run)
    extra = dict(run.extra or {})
    drafts = dict(extra.get("mail_drafts") or {})
    current = next((r for r in rows if str(r.get("mail_id")) == str(mail_id)), None)
    if current is None:
        raise KeyError(f"mail {mail_id} not found")
    if str(current.get("send_status") or "draft") != "draft":
        raise ValueError("only draft replies can be edited")
    patch = dict(drafts.get(str(mail_id)) or {})
    if to_address is not None:
        patch["to_address"] = to_address.strip()
    if draft_subject is not None:
        patch["draft_subject"] = draft_subject
    if draft_body is not None:
        patch["draft_body"] = draft_body
    drafts[str(mail_id)] = patch
    extra["mail_drafts"] = drafts
    run.extra = extra
    updated = collect_mail_rows(run)
    extra["mail_rows"] = updated
    run.extra = extra
    return next(r for r in updated if str(r.get("mail_id")) == str(mail_id))


def apply_mail_actions(
    run: Any,
    pipeline: Any,
    *,
    action: str,
    mail_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    rows = collect_mail_rows(run)
    wanted = {str(i) for i in (mail_ids or [])}
    if action == "send_all":
        targets = [r for r in rows if str(r.get("send_status") or "draft") == "draft"]
    else:
        targets = [r for r in rows if str(r.get("mail_id")) in wanted]
    cfg = mailbox_node_config(pipeline)
    extra = dict(run.extra or {})
    actions = dict(extra.get("mail_actions") or {})
    status = "sent" if action in {"send", "send_all"} else "skipped"
    for row in targets:
        mid = str(row.get("mail_id"))
        if action in {"send", "send_all"}:
            to_addr = str(row.get("to_address") or _email_from_from(str(row.get("from") or "")))
            if to_addr:
                send_smtp(
                    cfg,
                    to_addr=to_addr,
                    subject=str(row.get("draft_subject") or f"Re: {row.get('subject') or 'PR'}"),
                    body=str(row.get("draft_body") or ""),
                )
        actions[mid] = status
        row["send_status"] = status
    extra["mail_actions"] = actions
    extra["mail_rows"] = rows
    run.extra = extra
    return rows
