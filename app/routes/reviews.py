from fastapi import APIRouter, HTTPException, Header
from typing import Optional
from app.database import supabase
from app.models.review_models import CreateReviewRequest
from app.services.review_service import (
    create_review,
    get_product_reviews,
    get_product_review_stats,
    has_user_reviewed,
)
from app.services.user_service import is_author


public_reviews_router = APIRouter(
    prefix="/rdzd/reviews",
    tags=["Public Reviews"],
)

auth_reviews_router = APIRouter(
    prefix="/rdzd/reviews",
    tags=["Auth Reviews"],
)


def _get_authenticated_user_id(authorization: Optional[str]):
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")

    token = authorization.replace("Bearer ", "")
    try:
        response = supabase.auth.get_user(token)
        user = None
        if hasattr(response, "user") and response.user:
            user = response.user
        elif isinstance(response, dict):
            user = response.get("user")

        user_id = None
        if isinstance(user, dict):
            user_id = user.get("id")
        elif user is not None:
            user_id = getattr(user, "id", None)

        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        return user_id
    except HTTPException:
        raise
    except Exception as e:
        print("AUTH ERROR IN REVIEWS:", e)
        raise HTTPException(status_code=401, detail="Invalid or expired token")


# ─── Public: list reviews for a product ───────────────────────────────────────


@public_reviews_router.get("/{product_id}")
def list_product_reviews(product_id: str):
    try:
        reviews = get_product_reviews(product_id)
        stats = get_product_review_stats(product_id)

        return {
            "reviews": reviews,
            "stats": stats,
        }
    except Exception as e:
        print("LIST REVIEWS ERROR:", e)
        raise HTTPException(status_code=400, detail=str(e))


# ─── Auth: create a review ────────────────────────────────────────────────────


@auth_reviews_router.post("")
def create_product_review(
    payload: CreateReviewRequest,
    authorization: Optional[str] = Header(None),
):
    try:
        user_id = _get_authenticated_user_id(authorization)

        if is_author(user_id):
            raise HTTPException(
                status_code=403,
                detail="Admins cannot review products.",
            )

        if has_user_reviewed(user_id, payload.product_id):
            raise HTTPException(
                status_code=409,
                detail="You have already reviewed this product.",
            )

        # Fetch user name from the users table
        user_result = (
            supabase.table("users")
            .select("name")
            .eq("user_id", user_id)
            .execute()
        )
        user_name = "Anonymous"
        if hasattr(user_result, "data") and user_result.data:
            user_name = user_result.data[0].get("name", "Anonymous")
        elif isinstance(user_result, dict):
            data = user_result.get("data") or []
            if data:
                user_name = data[0].get("name", "Anonymous")

        review = create_review(
            user_id=user_id,
            user_name=user_name,
            product_id=payload.product_id,
            rating=payload.rating,
            feedback=payload.feedback,
        )

        if not review:
            raise HTTPException(status_code=500, detail="Failed to create review")

        return {
            "message": "Review submitted successfully",
            "review": review,
        }

    except HTTPException:
        raise
    except Exception as e:
        print("CREATE REVIEW ERROR:", e)
        raise HTTPException(status_code=400, detail=str(e))
