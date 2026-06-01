from pydantic import BaseModel, Field
from typing import List, Optional


class AttributeItem(BaseModel):
    key: str
    value: str


class CreateProductRequest(BaseModel):
    title: str
    description: str
    category: str
    cover_image_url: Optional[str] = None
    screenshots: List[str] = Field(default_factory=list)
    tools: List[str]
    price: float
    original_price: Optional[float] = None
    attributes: List[AttributeItem] = Field(default_factory=list)


class ProductResponse(BaseModel):
    id: str
    author_id: str
    user_id: str
    category: str
    status: str
    created_at: str
    updated_at: str


class CloudinaryUploadResponse(BaseModel):
    url: str
    public_id: str
    secure_url: str
    resource_type: str
