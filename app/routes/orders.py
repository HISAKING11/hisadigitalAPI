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


def _extract_data(response):
    if hasattr(response, "data"):
        return response.data
    if isinstance(response, dict):
        return response.get("data")
    return None


def _get_authenticated_user(authorization: Optional[str]):
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")

    token = authorization.replace("Bearer ", "")
    user_data = supabase.auth.get_user(token)
    user = user_data.user if hasattr(user_data, "user") else (user_data.get("user") if isinstance(user_data, dict) else None)

    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = getattr(user, "id", None) or (user.get("id") if isinstance(user, dict) else None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Could not extract user id from token")

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

        order_insert = admin_supabase.table("orders").insert({
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
            final_order_status = "email_sent"
            final_email_status = "sent"
        elif admin_email_status == "failed" and reply_email_status == "failed":
            final_order_status = "email_failed"
            final_email_status = "failed"
        else:
            final_order_status = "email_partial"
            final_email_status = "partial"

        admin_supabase.table("orders").update({"status": final_order_status, "email_status": final_email_status}).eq("id", order_id).execute()

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
