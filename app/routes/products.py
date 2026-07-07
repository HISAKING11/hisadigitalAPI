from fastapi import APIRouter, HTTPException, Header, File, UploadFile, Query
from typing import Optional, List
from uuid import uuid4
from pathlib import Path
from app.database import supabase, admin_supabase
from app.models.products_models import CreateProductRequest, CloudinaryUploadResponse
from app.services.cloudinary_service import upload_image_to_cloudinary
from app.services.review_service import get_product_review_stats


products_router = APIRouter(
    prefix="/rdzd/author/products",
    tags=["Author Products"]
)

public_products_router = APIRouter(
    prefix="/rdzd/products",
    tags=["Public Products"]
)


def _extract_user_id_from_token(token: Optional[str] = None):
    """Extract user_id from JWT token or return None"""
    if not token:
        return None
    
    try:
        # Supabase JWT verification would go here
        # For now, we'll rely on the client to send user_id
        decoded = supabase.auth.get_user(token)
        if hasattr(decoded, "user") and decoded.user:
            return getattr(decoded.user, "id", None)
        return None
    except Exception:
        return None


def _extract_data(response):
    if hasattr(response, "data"):
        return response.data

    if isinstance(response, dict):
        return response.get("data")

    return None


def _first_related_item(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _get_authenticated_author(authorization: Optional[str]):
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
        print("AUTH GET USER ERROR IN PRODUCTS.PY:", e)
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    author_check = admin_supabase.table("authors").select("id").eq("user_id", user_id).execute()
    author_data = _extract_data(author_check) or []

    if not author_data:
        raise HTTPException(status_code=403, detail="User is not registered as an author")

    return user_id, author_data[0]["id"]


def _template_payload(product: CreateProductRequest, product_id: str, author_id: str):
    """
    Build the database payload for a template product.

    cover_image_url and screenshots should contain Cloudinary URLs once the
    Cloudinary upload flow is implemented.
    """
    return {
        "product_id": product_id,
        "author_id": author_id,
        "title": product.title,
        "description": product.description,
        "cover_image_url": product.cover_image_url,
        "screenshots": product.screenshots,
        "tools": product.tools,
        "price": product.price,
        "original_price": product.original_price,
        "attributes": [{"key": attr.key, "value": attr.value} for attr in product.attributes],
        "download_url": product.download_url
    }


def _require_template_category(product: CreateProductRequest):
    allowed_categories = {"template", "mobile_ui"}
    if product.category not in allowed_categories:
        raise HTTPException(
            status_code=400,
            detail="Only template and mobile_ui products are supported until the category-specific table is added"
        )


def _detail_table_name(category: str) -> str:
    return "mobile_ui" if category == "mobile_ui" else "templates"


def _detail_key(category: str) -> str:
    return "mobile_ui" if category == "mobile_ui" else "templates"


def _serialize_public_product(product: dict):
    category = product.get("category", "template")
    detail = _first_related_item(product.get(_detail_key(category))) or {}
    author = _first_related_item(product.get("authors")) or {}
    author_profile_image = author.get("profile_url") or author.get("cover_img_url")
    product_id = product.get("id")

    stats = get_product_review_stats(product_id) if product_id else {"avg_rating": 0, "reviews_count": 0}

    return {
        "id": product_id,
        "category": category,
        "status": product.get("status"),
        "created_at": product.get("created_at"),
        "updated_at": product.get("updated_at"),
        "title": detail.get("title"),
        "description": detail.get("description"),
        "cover_image_url": detail.get("cover_image_url"),
        "screenshots": detail.get("screenshots") or [],
        "tools": detail.get("tools") or [],
        "price": detail.get("price"),
        "original_price": detail.get("original_price"),
        "attributes": detail.get("attributes") or [],
        "author_name": author.get("name"),
        "author_avatar": author_profile_image,
        "author_cover_image": author.get("cover_img_url"),
        "author_id": product.get("author_id"),
        "avg_rating": stats["avg_rating"],
        "reviews_count": stats["reviews_count"],
    }


# -----------------------------------
# PUBLIC PRODUCTS
# -----------------------------------


@public_products_router.get("/list")
def list_public_products(
    page: int = Query(1, ge=1),
    limit: int = Query(12, ge=1, le=100),
    search: Optional[str] = Query(None),
    category: Optional[str] = Query(None)
):
    """
    Get published products for public marketplace pages.

    No authentication required. Only publicly visible published products
    are returned.
    """
    try:
        base_select = "id, author_id, category, status, created_at, updated_at, authors(name, profile_url, cover_img_url)"

        t_result = (
            admin_supabase.table("products")
            .select(f"{base_select}, templates(*)")
            .eq("status", "published")
            .eq("category", "template")
            .order("created_at", desc=True)
            .execute()
        )

        m_result = (
            admin_supabase.table("products")
            .select(f"{base_select}, mobile_ui(*)")
            .eq("status", "published")
            .eq("category", "mobile_ui")
            .order("created_at", desc=True)
            .execute()
        )

        products = (_extract_data(t_result) or []) + (_extract_data(m_result) or [])
        products.sort(key=lambda p: p.get("created_at", ""), reverse=True)

        if category:
            products = [product for product in products if product.get("category") == category]

        if search:
            search_text = search.strip().lower()
            filtered_products = []

            for product in products:
                cat = product.get("category", "template")
                detail = _first_related_item(product.get(_detail_key(cat))) or {}
                haystack = " ".join([
                    str(detail.get("title") or ""),
                    str(detail.get("description") or ""),
                    str(cat),
                ]).lower()

                if search_text in haystack:
                    filtered_products.append(product)

            products = filtered_products

        total = len(products)
        start = (page - 1) * limit
        end = start + limit
        paginated_products = products[start:end]

        return {
            "message": "Public products retrieved successfully",
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": (total + limit - 1) // limit if total else 0,
            "products": [_serialize_public_product(product) for product in paginated_products],
        }

    except Exception as e:
        print("LIST PUBLIC PRODUCTS ERROR:", e)
        raise HTTPException(status_code=400, detail=str(e))


# -----------------------------------
# CREATE PRODUCT
# -----------------------------------


@products_router.post("/create")
def create_product(
    product: CreateProductRequest,
    authorization: Optional[str] = Header(None)
):
    """
    Create a new digital product for the authenticated author.
    
    Requires Authorization header with Supabase JWT token.
    """
    try:
        _require_template_category(product)
        user_id, author_id = _get_authenticated_author(authorization)

        # Insert parent product row first, then template-specific details.
        product_insert = admin_supabase.table("products").insert({
            "author_id": author_id,
            "user_id": user_id,
            "category": product.category,
            "status": "published"
        }).execute()

        product_data = _extract_data(product_insert)
        
        if not product_data:
            raise HTTPException(status_code=500, detail="Failed to create product")

        product_row = product_data[0] if isinstance(product_data, list) else product_data
        product_id = product_row["id"]
        detail_table = _detail_table_name(product.category)

        detail_insert = admin_supabase.table(detail_table).insert(
            _template_payload(product, product_id, author_id)
        ).execute()

        detail_data = _extract_data(detail_insert)

        if not detail_data:
            admin_supabase.table("products").delete().eq("id", product_id).eq("author_id", author_id).execute()
            raise HTTPException(status_code=500, detail=f"Failed to create {detail_table} details")

        detail_row = detail_data[0] if isinstance(detail_data, list) else detail_data

        return {
            "message": "Product created successfully",
            "product": {
                **product_row,
                _detail_key(product.category): detail_row
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        print("CREATE PRODUCT ERROR:", e)
        raise HTTPException(status_code=400, detail=str(e))


# -----------------------------------
# GET AUTHOR PRODUCTS
# -----------------------------------


@products_router.get("/list")
def list_author_products(authorization: Optional[str] = Header(None)):
    """
    Get all products for the authenticated author.
    """
    try:
        _, author_id = _get_authenticated_author(authorization)

        t_result = (
            admin_supabase.table("products")
            .select("*, templates(*)")
            .eq("author_id", author_id)
            .eq("category", "template")
            .order("created_at", desc=True)
            .execute()
        )

        m_result = (
            admin_supabase.table("products")
            .select("*, mobile_ui(*)")
            .eq("author_id", author_id)
            .eq("category", "mobile_ui")
            .order("created_at", desc=True)
            .execute()
        )

        products = (_extract_data(t_result) or []) + (_extract_data(m_result) or [])

        return {
            "message": "Products retrieved successfully",
            "count": len(products),
            "products": products
        }

    except HTTPException:
        raise
    except Exception as e:
        print("LIST PRODUCTS ERROR:", e)
        raise HTTPException(status_code=400, detail=str(e))


# -----------------------------------
# GET PRODUCT BY ID
# -----------------------------------


@products_router.get("/{product_id}")
def get_product(product_id: str, authorization: Optional[str] = Header(None)):
    """
    Get a specific product by id. Only authors can view their own products.
    """
    try:
        _, author_id = _get_authenticated_author(authorization)

        product_result = (
            admin_supabase.table("products")
            .select("*")
            .eq("id", product_id)
            .eq("author_id", author_id)
            .execute()
        )

        products = _extract_data(product_result) or []

        if not products:
            raise HTTPException(status_code=404, detail="Product not found or access denied")

        product = products[0]
        cat = product.get("category", "template")
        detail_table = _detail_table_name(cat)

        detail_result = (
            admin_supabase.table(detail_table)
            .select("*")
            .eq("product_id", product_id)
            .execute()
        )

        detail_data = _extract_data(detail_result) or []
        product[_detail_key(cat)] = detail_data[0] if detail_data else {}

        return {
            "message": "Product retrieved successfully",
            "product": product
        }

    except HTTPException:
        raise
    except Exception as e:
        print("GET PRODUCT ERROR:", e)
        raise HTTPException(status_code=400, detail=str(e))


# -----------------------------------
# UPDATE PRODUCT
# -----------------------------------


@products_router.put("/{product_id}")
def update_product(
    product_id: str,
    product: CreateProductRequest,
    authorization: Optional[str] = Header(None)
):
    """
    Update a product. Only the author who created it can update.
    """
    try:
        _require_template_category(product)
        _, author_id = _get_authenticated_author(authorization)

        # Verify ownership
        check = (
            admin_supabase.table("products")
            .select("id, category")
            .eq("id", product_id)
            .eq("author_id", author_id)
            .execute()
        )
        check_data = _extract_data(check) or []
        
        if not check_data:
            raise HTTPException(status_code=404, detail="Product not found or access denied")

        old_category = check_data[0]["category"]
        new_category = product.category

        # Update parent category
        product_update = (
            admin_supabase.table("products")
            .update({"category": new_category})
            .eq("id", product_id)
            .eq("author_id", author_id)
            .execute()
        )
        product_data = _extract_data(product_update) or []

        old_table = _detail_table_name(old_category)
        new_table = _detail_table_name(new_category)

        # If category changed, delete old detail row and insert into new table
        if old_table != new_table:
            admin_supabase.table(old_table).delete().eq("product_id", product_id).execute()
            detail_insert = admin_supabase.table(new_table).insert(
                _template_payload(product, product_id, author_id)
            ).execute()
        else:
            detail_insert = admin_supabase.table(new_table).update(
                _template_payload(product, product_id, author_id)
            ).eq("product_id", product_id).eq("author_id", author_id).execute()

        updated_data = _extract_data(detail_insert) or []

        if not product_data or not updated_data:
            raise HTTPException(status_code=500, detail="Failed to update product")

        return {
            "message": "Product updated successfully",
            "product": {
                **product_data[0],
                _detail_key(new_category): updated_data[0] if isinstance(updated_data, list) else updated_data
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        print("UPDATE PRODUCT ERROR:", e)
        raise HTTPException(status_code=400, detail=str(e))


# -----------------------------------
# DELETE PRODUCT
# -----------------------------------


@products_router.delete("/{product_id}")
def delete_product(product_id: str, authorization: Optional[str] = Header(None)):
    """
    Delete a product. Only the author who created it can delete.
    """
    try:
        _, author_id = _get_authenticated_author(authorization)

        # Fetch product to determine detail table
        check = (
            admin_supabase.table("products")
            .select("id, category")
            .eq("id", product_id)
            .eq("author_id", author_id)
            .execute()
        )
        check_data = _extract_data(check) or []

        if not check_data:
            raise HTTPException(status_code=404, detail="Product not found or access denied")

        cat = check_data[0].get("category", "template")

        # Delete from detail table first
        admin_supabase.table(_detail_table_name(cat)).delete().eq("product_id", product_id).execute()

        # Delete parent product
        product_delete = (
            admin_supabase.table("products")
            .delete()
            .eq("id", product_id)
            .eq("author_id", author_id)
            .execute()
        )

        deleted_data = _extract_data(product_delete) or []

        if not deleted_data:
            raise HTTPException(status_code=404, detail="Product not found or access denied")

        return {
            "message": "Product deleted successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        print("DELETE PRODUCT ERROR:", e)
        raise HTTPException(status_code=400, detail=str(e))


# -----------------------------------
# UPLOAD IMAGES TO CLOUDINARY
# -----------------------------------


@products_router.post("/upload/cover")
async def upload_cover_image(
    file: UploadFile = File(...),
    authorization: Optional[str] = Header(None)
):
    """
    Upload a cover image to Cloudinary and return the URL.
    The URL will be saved in Supabase when creating/updating a product.
    """
    try:
        user_id, author_id = _get_authenticated_author(authorization)
        
        # Read file content
        content = await file.read()
        
        # Upload to Cloudinary
        result = upload_image_to_cloudinary(content, file.filename)
        
        return {
            "message": "Cover image uploaded successfully",
            "upload": {
                "url": result.get("secure_url"),
                "secure_url": result.get("secure_url"),
                "public_id": result.get("public_id"),
                "resource_type": result.get("resource_type")
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        print("UPLOAD COVER IMAGE ERROR:", e)
        raise HTTPException(status_code=400, detail=str(e))


@products_router.post("/upload/screenshots")
async def upload_screenshots(
    files: List[UploadFile] = File(...),
    authorization: Optional[str] = Header(None)
):
    """
    Upload multiple screenshot images to Cloudinary and return URLs.
    The URLs will be saved in Supabase when creating/updating a product.
    """
    try:
        user_id, author_id = _get_authenticated_author(authorization)
        
        uploaded_urls = []
        
        for file in files:
            content = await file.read()
            result = upload_image_to_cloudinary(content, file.filename)
            
            uploaded_urls.append({
                "url": result.get("secure_url"),
                "secure_url": result.get("secure_url"),
                "public_id": result.get("public_id"),
                "resource_type": result.get("resource_type")
            })
        
        return {
            "message": "Screenshots uploaded successfully",
            "count": len(uploaded_urls),
            "uploads": uploaded_urls
        }
    
    except HTTPException:
        raise
    except Exception as e:
        print("UPLOAD SCREENSHOTS ERROR:", e)
        raise HTTPException(status_code=400, detail=str(e))


@products_router.post("/upload/file")
async def upload_product_file(
    file: UploadFile = File(...),
    authorization: Optional[str] = Header(None)
):
    """
    Upload a product file (zip) to Supabase storage 'products' bucket and return the URL.
    The URL will be saved in Supabase when creating/updating a product.
    """
    try:
        user_id, author_id = _get_authenticated_author(authorization)
        
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="File is empty")
        
        suffix = Path(file.filename or "").suffix.lower()
        if suffix != ".zip":
            raise HTTPException(status_code=400, detail="Only ZIP files are allowed")
            
        storage_path = f"{author_id}/{uuid4().hex}.zip"
        storage = admin_supabase.storage.from_("products")
        storage.upload(
            storage_path,
            content,
            file_options={"content-type": "application/zip"}
        )
        
        return {
    "message": "Product file uploaded successfully",
    "url": storage_path,   # ✅ just the path, e.g. "products/author-id/abc123.zip"
    "storage_path": storage_path
}
    
    except HTTPException:
        raise
    except Exception as e:
        print("UPLOAD PRODUCT FILE ERROR:", e)
        raise HTTPException(status_code=400, detail=str(e))
