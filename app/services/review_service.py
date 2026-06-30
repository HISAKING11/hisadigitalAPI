from datetime import datetime, timezone
from typing import Optional
from app.database import admin_supabase


def _extract_data(response):
    if hasattr(response, "data"):
        return response.data or []
    if isinstance(response, dict):
        return response.get("data") or []
    return []


def create_review(user_id: str, user_name: str, product_id: str, rating: int, feedback: Optional[str] = None):
    result = admin_supabase.table("reviews").insert({
        "user_id": user_id,
        "product_id": product_id,
        "rating": rating,
        "feedback": feedback or "",
        "user_name": user_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }).execute()

    data = _extract_data(result)
    return data[0] if data else None


def get_product_reviews(product_id: str):
    result = (
        admin_supabase.table("reviews")
        .select("*")
        .eq("product_id", product_id)
        .order("created_at", desc=True)
        .execute()
    )
    return _extract_data(result)


def get_product_review_stats(product_id: str):
    result = (
        admin_supabase.table("reviews")
        .select("rating")
        .eq("product_id", product_id)
        .execute()
    )
    ratings = _extract_data(result)
    if not ratings:
        return {"avg_rating": 0, "reviews_count": 0}

    total = sum(r["rating"] for r in ratings)
    count = len(ratings)
    return {"avg_rating": round(total / count, 1), "reviews_count": count}


def has_user_reviewed(user_id: str, product_id: str) -> bool:
    result = (
        admin_supabase.table("reviews")
        .select("id")
        .eq("user_id", user_id)
        .eq("product_id", product_id)
        .execute()
    )
    data = _extract_data(result)
    return len(data) > 0
