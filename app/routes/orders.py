from fastapi import APIRouter, HTTPException, Header
from typing import Optional
import os
import time
from app.database import supabase, admin_supabase
from app.models.order_models import PlaceOrderRequest
from app.services.email_service import send_emailjs_template


orders_router = APIRouter(
    prefix="/rdzd/orders",
    tags=["Orders"]
)

ORDER_TABLE = os.getenv("ORDER_TABLE", "orders")

CLIENT_PENDING_STATUSES = {"pending", "email_sent", "email_failed", "email_partial"}
CLIENT_VERIFIED_STATUSES = {"verified", "paid", "payment_complete", "completed"}
CLIENT_CANCELED_STATUSES = {"canceled", "cancelled", "cancel"}


def _extract_data(response):
    if hasattr(response, "data"):
        return response.data
    if isinstance(response, dict):
        return response.get("data")
    return None


def _normalize_dashboard_status(status: Optional[str]) -> str:
    value = (status or "pending").lower()
    if value in CLIENT_VERIFIED_STATUSES:
        return "verified"
    if value in CLIENT_CANCELED_STATUSES:
        return "canceled"
    if value in CLIENT_PENDING_STATUSES:
        return "pending"
    return "pending"


def _line_total(item: dict) -> float:
    if item.get("line_total") is not None:
        return float(item.get("line_total") or 0)
    return float(item.get("unit_price") or 0) * int(item.get("quantity") or 1)


def _download_url_from_product(product: dict) -> Optional[str]:
    template = product.get("templates")
    if isinstance(template, list):
        template = template[0] if template else {}
    if not isinstance(template, dict):
        template = {}

    for key in ("download_url", "file_url", "source_url", "asset_url", "zip_url"):
        if template.get(key):
            return template.get(key)

    for attr in template.get("attributes") or []:
        if not isinstance(attr, dict):
            continue
        key = str(attr.get("key") or "").lower()
        if key in {"download_url", "download url", "file_url", "file url", "source_url", "source url", "zip_url", "zip url"}:
            value = attr.get("value")
            if value:
                return value

    return None


def _serialize_order(order: dict, items: list) -> dict:
    raw_status = order.get("status")
    status = _normalize_dashboard_status(raw_status)
    order_number = order.get("order_number") or str(order.get("id") or "")[:8]

    return {
        "id": order.get("id"),
        "order_number": order_number,
        "created_at": order.get("created_at"),
        "status": status,
        "raw_status": raw_status,
        "email_status": order.get("email_status"),
        "total": float(order.get("total") or 0),
        "currency": order.get("currency") or "INR",
        "items": [
            {
                "id": item.get("id"),
                "product_id": item.get("product_id"),
                "product_name": item.get("product_name"),
                "quantity": int(item.get("quantity") or 1),
                "unit_price": float(item.get("unit_price") or 0),
                "line_total": _line_total(item),
            }
            for item in items
        ],
        "download_url": order.get("download_url") if status == "verified" else None,
        "payment_url": order.get("payment_url") if status == "pending" else None,
    }


def _get_user_order(order_id: str, user_id: str) -> dict:
    result = (
        admin_supabase.table(ORDER_TABLE)
        .select("*")
        .eq("id", order_id)
        .eq("user_id", user_id)
        .execute()
    )
    orders = _extract_data(result) or []
    if not orders:
        raise HTTPException(status_code=404, detail="Order not found")
    return orders[0]


def _get_order_items(order_id: str) -> list:
    result = (
        admin_supabase.table("order_items")
        .select("*")
        .eq("order_id", order_id)
        .order("created_at", desc=False)
        .execute()
    )
    return _extract_data(result) or []


def _get_download_url_for_order(order: dict, items: list) -> Optional[str]:
    if order.get("download_url"):
        return order.get("download_url")

    product_ids = [item.get("product_id") for item in items if item.get("product_id")]
    if not product_ids:
        return None

    products_result = (
        admin_supabase.table("products")
        .select("id, templates(*)")
        .in_("id", product_ids)
        .execute()
    )
    products = _extract_data(products_result) or []
    for product in products:
        url = _download_url_from_product(product)
        if url:
            return url

    return None


def _get_authenticated_user(authorization: Optional[str]):
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")

    token = authorization.replace("Bearer ", "")
    try:
        user_data = supabase.auth.get_user(token)
        user = user_data.user if hasattr(user_data, "user") else (user_data.get("user") if isinstance(user_data, dict) else None)

        if not user:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        user_id = getattr(user, "id", None) or (user.get("id") if isinstance(user, dict) else None)
        if not user_id:
            raise HTTPException(status_code=401, detail="Could not extract user id from token")
    except Exception as e:
        print("AUTH GET USER ERROR IN ORDERS.PY:", e)
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return user_id, user


def _build_product_summary(items):
    labels = []
    for item in items:
        prefix = f"{item.quantity}x " if item.quantity > 1 else ""
        labels.append(f"{prefix}{item.product_name}")
    return ", ".join(labels)


def _build_product_id_summary(items):
    ids = []
    for item in items:
        prefix = f"{item.quantity}x " if item.quantity > 1 else ""
        ids.append(f"{prefix}{item.product_id}")
    return ", ".join(ids)


def _insert_order_email_log(order_id: str, email_type: str, template_id: str, recipient_email: str, status: str, error_message: Optional[str] = None):
    admin_supabase.table("order_email_logs").insert({
        "order_id": order_id,
        "email_type": email_type,
        "template_id": template_id,
        "recipient_email": recipient_email,
        "status": status,
        "error_message": error_message,
    }).execute()


@orders_router.get("/mine")
def list_my_orders(authorization: Optional[str] = Header(None)):
    try:
        user_id, _user = _get_authenticated_user(authorization)

        order_result = (
            admin_supabase.table(ORDER_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        orders = _extract_data(order_result) or []

        order_ids = [order.get("id") for order in orders if order.get("id")]
        items_by_order = {order_id: [] for order_id in order_ids}

        if order_ids:
            item_result = (
                admin_supabase.table("order_items")
                .select("*")
                .in_("order_id", order_ids)
                .order("created_at", desc=False)
                .execute()
            )
            for item in _extract_data(item_result) or []:
                items_by_order.setdefault(item.get("order_id"), []).append(item)

        return {
            "message": "Orders retrieved successfully",
            "orders": [_serialize_order(order, items_by_order.get(order.get("id"), [])) for order in orders],
        }

    except HTTPException:
        raise
    except Exception as e:
        print("LIST MY ORDERS ERROR:", e)
        raise HTTPException(status_code=400, detail=str(e))


@orders_router.post("/{order_id}/cancel")
def cancel_order(order_id: str, authorization: Optional[str] = Header(None)):
    try:
        user_id, _user = _get_authenticated_user(authorization)
        order = _get_user_order(order_id, user_id)
        status = _normalize_dashboard_status(order.get("status"))

        if status == "verified":
            raise HTTPException(status_code=400, detail="Verified orders cannot be canceled")
        if status == "canceled":
            items = _get_order_items(order_id)
            return {"message": "Order is already canceled", "order": _serialize_order(order, items)}

        update = (
            admin_supabase.table(ORDER_TABLE)
            .update({"status": "canceled"})
            .eq("id", order_id)
            .eq("user_id", user_id)
            .execute()
        )
        updated = _extract_data(update) or []
        updated_order = updated[0] if updated else _get_user_order(order_id, user_id)
        items = _get_order_items(order_id)

        return {"message": "Order canceled successfully", "order": _serialize_order(updated_order, items)}

    except HTTPException:
        raise
    except Exception as e:
        print("CANCEL ORDER ERROR:", e)
        raise HTTPException(status_code=400, detail=str(e))


@orders_router.post("/{order_id}/pay")
def complete_order_payment(order_id: str, authorization: Optional[str] = Header(None)):
    try:
        user_id, _user = _get_authenticated_user(authorization)
        order = _get_user_order(order_id, user_id)
        status = _normalize_dashboard_status(order.get("status"))

        if status == "canceled":
            raise HTTPException(status_code=400, detail="Canceled orders cannot be paid")

        if status != "verified":
            update = (
                admin_supabase.table(ORDER_TABLE)
                .update({"status": "verified"})
                .eq("id", order_id)
                .eq("user_id", user_id)
                .execute()
            )
            updated = _extract_data(update) or []
            order = updated[0] if updated else _get_user_order(order_id, user_id)

        items = _get_order_items(order_id)
        return {"message": "Payment completed successfully", "order": _serialize_order(order, items)}

    except HTTPException:
        raise
    except Exception as e:
        print("PAY ORDER ERROR:", e)
        raise HTTPException(status_code=400, detail=str(e))


@orders_router.get("/{order_id}/download")
def get_order_download(order_id: str, authorization: Optional[str] = Header(None)):
    try:
        user_id, _user = _get_authenticated_user(authorization)
        order = _get_user_order(order_id, user_id)

        if _normalize_dashboard_status(order.get("status")) != "verified":
            raise HTTPException(status_code=403, detail="Complete payment before downloading this order")

        items = _get_order_items(order_id)
        download_url = _get_download_url_for_order(order, items)

        if not download_url:
            raise HTTPException(status_code=404, detail="Download file is not configured for this order")

        return {"message": "Download is ready", "download_url": download_url}

    except HTTPException:
        raise
    except Exception as e:
        print("DOWNLOAD ORDER ERROR:", e)
        raise HTTPException(status_code=400, detail=str(e))


@orders_router.post("/place")
def place_order(order: PlaceOrderRequest, authorization: Optional[str] = Header(None)):
    try:
        user_id, _user = _get_authenticated_user(authorization)

        if not order.items:
            raise HTTPException(status_code=400, detail="Cart items are required")

        service_id = os.getenv("EMAILJS_SERVICE_ID")
        order_template_id = os.getenv("EMAILJS_ORDER_TEMPLATE_ID")
        reply_template_id = os.getenv("EMAILJS_REPLY_TEMPLATE_ID")
        public_key = os.getenv("EMAILJS_PUBLIC_KEY")
        private_key = os.getenv("EMAILJS_PRIVATE_KEY")
        admin_email = os.getenv("ORDER_ADMIN_EMAIL", "hisadigitalmarketservice@gmail.com")

        if not service_id or not order_template_id or not reply_template_id or not public_key:
            raise HTTPException(status_code=500, detail="Email service is not configured")

        order_insert = admin_supabase.table(ORDER_TABLE).insert({
            "user_id": user_id,
            "customer_name": order.customer_name,
            "customer_email": order.customer_email,
            "customer_phone": order.customer_phone,
            "subtotal": order.subtotal,
            "discount_percent": order.discount_percent,
            "discount_amount": order.discount_amount,
            "total": order.total,
            "currency": order.currency,
            "status": "pending",
            "email_status": "pending",
        }).execute()

        order_data = _extract_data(order_insert) or []
        order_row = order_data[0] if isinstance(order_data, list) else order_data

        if not order_row:
            raise HTTPException(status_code=500, detail="Failed to create order")

        order_id = order_row.get("id")
        if not order_id:
            raise HTTPException(status_code=500, detail="Failed to create order id")

        item_rows = []
        for item in order.items:
            item_rows.append({
                "order_id": order_id,
                "product_id": item.product_id,
                "product_name": item.product_name,
                "unit_price": item.unit_price,
                "quantity": item.quantity,
                "line_total": round(item.unit_price * item.quantity, 2),
            })

        admin_supabase.table("order_items").insert(item_rows).execute()

        order_date = order_row.get("created_at") or "Recently placed"
        product_name = _build_product_summary(order.items)
        product_id = _build_product_id_summary(order.items)

        order_payload = {
            "order_id": order_id,
            "customer_name": order.customer_name,
            "customer_email": order.customer_email,
            "customer_phone": order.customer_phone,
            "name": order.customer_name,
            "email": order.customer_email,
            "phone": order.customer_phone,
            "product_id": product_id,
            "product_name": product_name,
            "product_price": f"{order.currency} {order.total:.2f}",
            "order_date": order_date,
            "to_email": admin_email,
        }

        email_results = []
        admin_email_status = "sent"
        reply_email_status = "sent"

        try:
            send_emailjs_template(service_id, order_template_id, order_payload, public_key, private_key)
            _insert_order_email_log(order_id, "admin", order_template_id, admin_email, "sent")
            email_results.append({"email_type": "admin", "status": "sent"})
        except Exception as exc:
            _insert_order_email_log(order_id, "admin", order_template_id, admin_email, "failed", str(exc))
            admin_email_status = "failed"
            email_results.append({"email_type": "admin", "status": "failed", "error": str(exc)})

        try:
            reply_payload = {
                **order_payload,
                "to_email": order.customer_email,
            }
            time.sleep(1.1)
            send_emailjs_template(service_id, reply_template_id, reply_payload, public_key, private_key)
            _insert_order_email_log(order_id, "reply", reply_template_id, order.customer_email, "sent")
            email_results.append({"email_type": "reply", "status": "sent"})
        except Exception as exc:
            _insert_order_email_log(order_id, "reply", reply_template_id, order.customer_email, "failed", str(exc))
            reply_email_status = "failed"
            email_results.append({"email_type": "reply", "status": "failed", "error": str(exc)})

        if admin_email_status == "sent" and reply_email_status == "sent":
            final_email_status = "sent"
        elif admin_email_status == "failed" and reply_email_status == "failed":
            final_email_status = "failed"
        else:
            final_email_status = "partial"

        final_order_status = "pending"

        admin_supabase.table(ORDER_TABLE).update({"status": final_order_status, "email_status": final_email_status}).eq("id", order_id).execute()

        return {
            "message": "Order placed successfully",
            "order": {
                **order_row,
                "items": item_rows,
                "status": final_order_status,
                "email_status": final_email_status,
            }
            ,
            "email_results": email_results,
        }

    except HTTPException:
        raise
    except Exception as e:
        print("PLACE ORDER ERROR:", e)
        raise HTTPException(status_code=400, detail=str(e))
