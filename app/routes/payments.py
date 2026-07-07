import razorpay
import os
import hmac
import hashlib
from typing import Optional
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from app.database import supabase, admin_supabase
# from backend.server.app.routes import products

# ── Razorpay client ────────────────────────────────────────────────────────────
client = razorpay.Client(
    auth=(os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET"))
)

router = APIRouter(prefix="/payments", tags=["Payments"])

ORDER_TABLE = os.getenv("ORDER_TABLE", "orders")


# ── Helpers ────────────────────────────────────────────────────────────────────
def _extract_data(response):
    if hasattr(response, "data"):
        return response.data
    if isinstance(response, dict):
        return response.get("data")
    return None


def _get_authenticated_user(authorization: Optional[str]):
    """Validate Bearer token and return (user_id, user) – mirrors orders.py."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")

    token = authorization.replace("Bearer ", "")
    try:
        user_data = supabase.auth.get_user(token)
        user = (
            user_data.user
            if hasattr(user_data, "user")
            else (user_data.get("user") if isinstance(user_data, dict) else None)
        )
        if not user:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        user_id = getattr(user, "id", None) or (
            user.get("id") if isinstance(user, dict) else None
        )
        if not user_id:
            raise HTTPException(status_code=401, detail="Could not extract user id")
    except HTTPException:
        raise
    except Exception as e:
        print("AUTH GET USER ERROR IN PAYMENTS.PY:", e)
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return user_id, user


def _get_order(order_id: str, user_id: str) -> dict:
    result = (
        admin_supabase.table(ORDER_TABLE)
        .select("*")
        .eq("id", order_id)
        .eq("user_id", user_id)
        .execute()
    )
    rows = _extract_data(result) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Order not found")
    return rows[0]


def _update_order_verified(internal_order_id: str, payment_id: str):
    """
    Mark the order as 'verified'.
    Tries to also store razorpay_payment_id; if that column doesn't exist
    the update falls back to status-only so it never fails silently.
    """
    print(f"[PAYMENTS] Updating order {internal_order_id} → verified (payment: {payment_id})")
    try:
        result = (
            admin_supabase.table(ORDER_TABLE)
            .update({"status": "verified", "razorpay_payment_id": payment_id})
            .eq("id", internal_order_id)
            .execute()
        )
        rows = _extract_data(result) or []
        print(f"[PAYMENTS] DB update result (with payment_id): {rows}")
        if rows:
            return  # success
    except Exception as e:
        print(f"[PAYMENTS] Update with razorpay_payment_id failed ({e}), retrying without it")

    # Fallback: update status only (column may not exist)
    try:
        result = (
            admin_supabase.table(ORDER_TABLE)
            .update({"status": "verified"})
            .eq("id", internal_order_id)
            .execute()
        )
        rows = _extract_data(result) or []
        print(f"[PAYMENTS] DB update result (status only): {rows}")
        if not rows:
            raise RuntimeError(f"No rows updated for order {internal_order_id}")
    except Exception as e:
        print(f"[PAYMENTS] CRITICAL: Could not update order status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update order status: {e}")


# ── Request / Response models ──────────────────────────────────────────────────
class CreateOrderRequest(BaseModel):
    order_id: str  # internal DB order ID


class WebhookPayload(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    internal_order_id: Optional[str] = None  # passed by frontend – avoids extra Razorpay API call


# ── 1. Create Razorpay order ───────────────────────────────────────────────────
@router.post("/create-razorpay-order")
def create_razorpay_order(
    body: CreateOrderRequest,
    authorization: Optional[str] = Header(None),
):
    user_id, _user = _get_authenticated_user(authorization)
    order = _get_order(body.order_id, user_id)

    if order.get("status") not in {"pending", "email_sent", "email_failed", "email_partial"}:
        raise HTTPException(status_code=400, detail="Order is not payable")

    amount_in_paise = int(float(order.get("total", 0)) * 100)
    if amount_in_paise <= 0:
        raise HTTPException(status_code=400, detail="Invalid order amount")

    try:
        rz_order = client.order.create(
            {
                "amount": amount_in_paise,
                "currency": order.get("currency", "INR"),
                "receipt": str(body.order_id)[:40],
                "notes": {
                    "internal_order_id": str(body.order_id),
                    "user_id": str(user_id),
                },
            }
        )
    except Exception as e:
        print(f"[PAYMENTS] Razorpay order.create failed: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"Payment gateway error: {str(e)}"
        )

    return {
        "razorpay_order_id": rz_order["id"],
        "amount": rz_order["amount"],
        "currency": rz_order["currency"],
        "key_id": os.getenv("RAZORPAY_KEY_ID"),
    }


# ── 2. Verify payment signature & update DB ────────────────────────────────────
@router.post("/verify-payment")
def verify_payment(payload: WebhookPayload):
    """
    Called by the frontend after Razorpay checkout succeeds.
    Verifies the HMAC-SHA256 signature then marks the order as 'verified'.
    No auth header required – the signature itself is the proof of payment.
    """
    print(f"[PAYMENTS] verify-payment called: rz_order={payload.razorpay_order_id} payment={payload.razorpay_payment_id}")

    secret = os.getenv("RAZORPAY_KEY_SECRET", "")
    if not secret:
        raise HTTPException(status_code=500, detail="Payment secret not configured")

    # ── HMAC-SHA256 signature check ───────────────────────────────────────────
    body = f"{payload.razorpay_order_id}|{payload.razorpay_payment_id}"
    expected_sig = hmac.new(
        secret.encode(),
        body.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_sig, payload.razorpay_signature):
        print("[PAYMENTS] Signature mismatch!")
        raise HTTPException(status_code=400, detail="Invalid payment signature")

    print("[PAYMENTS] Signature verified ✓")

    # ── Resolve internal order ID ─────────────────────────────────────────────
    # Prefer the value sent directly by the frontend (avoids a Razorpay API round-trip).
    internal_order_id = payload.internal_order_id

    if not internal_order_id:
        # Fallback: fetch from Razorpay notes
        try:
            rz_order = client.order.fetch(payload.razorpay_order_id)
            # notes may be None if Razorpay returns an empty object
            notes = rz_order.get("notes") or {}
            internal_order_id = notes.get("internal_order_id")
            print(f"[PAYMENTS] Resolved internal_order_id from Razorpay notes: {internal_order_id}")
        except Exception as e:
            print(f"[PAYMENTS] Razorpay order.fetch failed: {e}")

    if not internal_order_id:
        raise HTTPException(
            status_code=502,
            detail="Could not determine internal order ID. Payment was collected – contact support.",
        )

    # ── Update DB ─────────────────────────────────────────────────────────────
    _update_order_verified(internal_order_id, payload.razorpay_payment_id)

    return {"status": "success", "order_id": internal_order_id}


# ── 3. Download gate ───────────────────────────────────────────────────────────
@router.get("/download/{order_id}")
def download_product(
    order_id: str,
    authorization: Optional[str] = Header(None),
):
    """
    Returns a time-limited signed download URL only when the order is 'verified'.
    Falls back to the download_url stored directly on the order / order_items
    (mirrors the logic in orders.py get_order_download).
    """
    user_id, _user = _get_authenticated_user(authorization)
    order = _get_order(order_id, user_id)

    raw_status = (order.get("status") or "").lower()
    VERIFIED = {"verified", "paid", "payment_complete", "completed"}
    if raw_status not in VERIFIED:
        raise HTTPException(status_code=403, detail="Payment not completed")

    # ── Try direct download_url on the order row ──────────────────────────────
    if order.get("download_url"):
        return {"download_url": order["download_url"]}

    # ── Try order_items → product → template ─────────────────────────────────
    items_result = (
        admin_supabase.table("order_items")
        .select("*")
        .eq("order_id", order_id)
        .execute()
    )
    items = _extract_data(items_result) or []

    product_ids = [item.get("product_id") for item in items if item.get("product_id")]
    if product_ids:
        t_result = (
            admin_supabase.table("products")
            .select("id, templates(*)")
            .in_("id", product_ids)
            .eq("category", "template")
            .execute()
        )
        m_result = (
            admin_supabase.table("products")
            .select("id, mobile_ui(*)")
            .in_("id", product_ids)
            .eq("category", "mobile_ui")
            .execute()
        )
        products = (_extract_data(t_result) or []) + (_extract_data(m_result) or [])
        print(f"[PAYMENTS] product_ids from order: {product_ids}")
        print(f"[PAYMENTS] products fetched: {products}")
        for product in products:
            template = product.get("templates") or product.get("mobile_ui")
            if isinstance(template, list):
                template = template[0] if template else {}
            if not isinstance(template, dict):
                continue

            file_path = None
            print(f"[PAYMENTS] raw file_path from template: '{file_path}'")
            for key in ("download_url", "file_url", "source_url", "asset_url", "zip_url"):
                if template.get(key):
                    file_path = template[key]
                    break

            if not file_path:
                for attr in template.get("attributes") or []:
                    if not isinstance(attr, dict):
                        continue
                    k = str(attr.get("key") or "").lower()
                    if k in {"download_url", "download url", "file_url", "file url",
                            "zip_url", "zip url"}:
                        v = attr.get("value")
                        if v:
                            file_path = v
                            break

            if not file_path:
                continue
            
            try:
                print(f"[PAYMENTS] Generating signed URL for: '{file_path}'")
                signed = admin_supabase.storage.from_("products").create_signed_url(
                    file_path, expires_in=300
                )
                url = signed.get("signedURL") or signed.get("signed_url")
                if url:
                    return {"download_url": url}
            except Exception as e:
                print(f"[PAYMENTS] SIGNED URL ERROR: {e}")

    # ── Try Supabase Storage signed URL via file_path on items ───────────────
    for item in items:
        file_path = item.get("file_path")
        if file_path:
            try:
                signed = supabase.storage.from_("product_media").create_signed_url(
                    file_path, expires_in=300
                )
                url = signed.get("signedURL") or signed.get("signed_url") or signed.get("data", {}).get("signedURL")
                if url:
                    return {"download_url": url}
            except Exception as e:
                print("SIGNED URL ERROR:", e)

    raise HTTPException(status_code=404, detail="Download file is not configured for this order")