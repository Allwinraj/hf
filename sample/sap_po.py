from __future__ import annotations

from typing import Any

import httpx

# Same values as test_api_sap.py. Replace SAP_PO_PASSWORD with the real password.
SAP_PO_BASE_URL = "https://my426575-api.s4hana.cloud.sap/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV"
SAP_PO_USERNAME = "PUR_CONTRACT_USER"
SAP_PO_PASSWORD = "xxxxxxx"
SAP_PO_COMPANY_CODE = "2000"
SAP_PO_CURRENCY = "INR"
SAP_PO_TYPE = "NB"
SAP_PO_PURCHASING_GROUP = "001"
SAP_PO_PURCHASING_ORG = "2000"
SAP_PO_SUPPLIER = "1000000"
SAP_PO_ACCOUNT_ASSIGNMENT_CATEGORY = "K"
SAP_PO_MATERIAL_GROUP = "P002"
SAP_PO_PLANT = "2001"
SAP_PO_PRODUCT_TYPE = "1"
SAP_PO_QTY_UNIT = "EA"
SAP_PO_COST_CENTER = "INPURSER"
SAP_PO_GL_ACCOUNT = "65001000"


def payload_from_mail_row(row: dict[str, Any]) -> dict[str, Any]:
    qty = row.get("qty")
    if qty in (None, ""):
        qty = 1
    amount = row.get("budget")
    if amount in (None, ""):
        amount = row.get("NetPriceAmount") or 0
    text = str(row.get("item") or row.get("PurchaseOrderItemText") or "Purchase request").strip()[:40]
    cost_centre = str(row.get("cost_centre") or SAP_PO_COST_CENTER).strip() or SAP_PO_COST_CENTER
    return {
        "CompanyCode": SAP_PO_COMPANY_CODE,
        "DocumentCurrency": SAP_PO_CURRENCY,
        "PurchaseOrderType": SAP_PO_TYPE,
        "PurchasingGroup": SAP_PO_PURCHASING_GROUP,
        "PurchasingOrganization": SAP_PO_PURCHASING_ORG,
        "Supplier": SAP_PO_SUPPLIER,
        "to_PurchaseOrderItem": {
            "results": [
                {
                    "AccountAssignmentCategory": SAP_PO_ACCOUNT_ASSIGNMENT_CATEGORY,
                    "MaterialGroup": SAP_PO_MATERIAL_GROUP,
                    "NetPriceAmount": str(amount),
                    "OrderQuantity": str(qty),
                    "Plant": SAP_PO_PLANT,
                    "ProductType": SAP_PO_PRODUCT_TYPE,
                    "PurchaseOrderItemText": text,
                    "PurchaseOrderQuantityUnit": SAP_PO_QTY_UNIT,
                    "to_AccountAssignment": {
                        "results": [
                            {
                                "CostCenter": cost_centre,
                                "GLAccount": SAP_PO_GL_ACCOUNT,
                            }
                        ]
                    },
                }
            ]
        },
    }


def extract_purchase_order(body: Any) -> str:
    if not isinstance(body, dict):
        return ""
    if body.get("PurchaseOrder"):
        return str(body["PurchaseOrder"])
    nested = body.get("d")
    if isinstance(nested, dict) and nested.get("PurchaseOrder"):
        return str(nested["PurchaseOrder"])
    return ""


def post_purchase_order(row: dict[str, Any]) -> dict[str, Any]:
    url = f"{SAP_PO_BASE_URL.rstrip('/')}/A_PurchaseOrder"
    payload = payload_from_mail_row(row)
    with httpx.Client(auth=(SAP_PO_USERNAME, SAP_PO_PASSWORD), timeout=60.0, follow_redirects=True) as session:
        token_resp = session.get(
            url,
            headers={"x-csrf-token": "Fetch", "Accept": "application/json"},
        )
        csrf_token = token_resp.headers.get("x-csrf-token")
        if not csrf_token:
            return {
                "ok": False,
                "status_code": token_resp.status_code,
                "PurchaseOrder": "",
                "error": token_resp.text[:2000] or "Failed to fetch CSRF token",
                "payload": payload,
            }
        resp = session.post(
            url,
            json=payload,
            headers={
                "x-csrf-token": csrf_token,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001
            body = {"raw": resp.text[:2000]}
        number = extract_purchase_order(body)
        return {
            "ok": bool(resp.is_success and number),
            "status_code": resp.status_code,
            "PurchaseOrder": number,
            "error": "" if resp.is_success else str(body)[:2000],
            "payload": payload,
            "response": body,
        }


def apply_sap_posts(
    run: Any,
    *,
    mail_ids: list[str] | None = None,
    post_all: bool = False,
) -> dict[str, Any]:
    from app.services.mail import collect_mail_rows

    rows = collect_mail_rows(run)
    wanted = {str(i) for i in (mail_ids or [])}
    if post_all:
        targets = [r for r in rows if str(r.get("send_status") or "draft") != "skipped"]
    else:
        targets = [r for r in rows if str(r.get("mail_id")) in wanted]
    extra = dict(run.extra or {})
    posted = dict(extra.get("mail_sap") or {})
    results: list[dict[str, Any]] = []
    for row in targets:
        mid = str(row.get("mail_id"))
        existing = posted.get(mid) if isinstance(posted.get(mid), dict) else {}
        if existing.get("PurchaseOrder"):
            item = dict(existing)
            item["mail_id"] = mid
            item["skipped"] = True
            results.append(item)
            row["sap_purchase_order"] = existing["PurchaseOrder"]
            row["sap_status"] = "posted"
            continue
        result = post_purchase_order(row)
        result["mail_id"] = mid
        posted[mid] = result
        row["sap_purchase_order"] = result.get("PurchaseOrder") or ""
        row["sap_status"] = "posted" if result.get("ok") else "failed"
        results.append(result)
    extra["mail_sap"] = posted
    extra["mail_rows"] = rows
    run.extra = extra
    return {"ok": all(r.get("ok") or r.get("skipped") for r in results) if results else True, "results": results, "rows": rows}
