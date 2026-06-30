from pydantic import BaseModel, Field
from typing import Optional


class CreateReviewRequest(BaseModel):
    product_id: str
    rating: int = Field(..., ge=1, le=5)
    feedback: Optional[str] = None


class ReviewResponse(BaseModel):
    id: str
    user_id: str
    product_id: str
    rating: int
    feedback: Optional[str] = None
    user_name: str
    created_at: str
