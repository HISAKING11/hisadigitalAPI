from pydantic import BaseModel, Field
from typing import List, Optional


class OrderItemRequest(BaseModel):
    product_id: str
    product_name: str
    quantity: int = Field(..., ge=1)
    unit_price: float = Field(..., ge=0)


class PlaceOrderRequest(BaseModel):
    customer_name: str
    customer_email: str
    customer_phone: str
    items: List[OrderItemRequest] = Field(default_factory=list)
    subtotal: float = Field(..., ge=0)
    discount_percent: int = Field(default=0, ge=0, le=100)
    discount_amount: float = Field(default=0, ge=0)
    total: float = Field(..., ge=0)
    currency: str = Field(default="INR")


class OrderEmailLog(BaseModel):
    email_type: str
    template_id: str
    recipient_email: str
    status: str
    error_message: Optional[str] = None


class OrderStatusUpdateResponse(BaseModel):
    message: str
    order: dict
