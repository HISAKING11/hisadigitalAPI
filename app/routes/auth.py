from fastapi import APIRouter, HTTPException, Header, File, UploadFile
from app.database import supabase, admin_supabase
from app.models.auth_models import RegisterRequest, LoginRequest
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path
from uuid import uuid4


router = APIRouter(
    prefix="/rdzd/auth",
    tags=["Auth"]
)

author_router = APIRouter(
    prefix="/rdzd/auth/author",
    tags=["Author Auth"]
)

PROFILE_BUCKET = "profile"
AUTHOR_PROFILE_SELECT = "id, user_id, name, phone, email, profile_url, cover_img_url, created_at"
USER_PROFILE_SELECT = "id, user_id, name, phone, email, profile_url,cover_img_url, created_at"


def _extract_response_user(response):
    if hasattr(response, "user") and response.user:
        return response.user

    if isinstance(response, dict):
        return response.get("user")

    return None


def _extract_user_id(response):
    user_obj = _extract_response_user(response)

    if isinstance(user_obj, dict):
        return user_obj.get("id")

    if user_obj is not None:
        return getattr(user_obj, "id", None)

    return None


def _extract_session(response):
    if hasattr(response, "session") and response.session:
        return response.session

    if isinstance(response, dict):
        return response.get("session")

    return None


def _profile_select_for_table(table_name: str):
    return AUTHOR_PROFILE_SELECT if table_name == "authors" else USER_PROFILE_SELECT


def _normalize_profile(table_name: str, profile):
    if not profile:
        return profile

    if table_name == "authors":
        profile = {
            **profile,
            "avatar_url": profile.get("profile_url") or profile.get("cover_img_url"),
        }

    return profile


def _fetch_profile(table_name: str, user_id: str):
    result = admin_supabase.table(table_name).select(_profile_select_for_table(table_name)).eq("user_id", user_id).execute()

    if hasattr(result, "data"):
        return _normalize_profile(table_name, result.data[0]) if result.data else None

    if isinstance(result, dict):
        data = result.get("data") or []
        return _normalize_profile(table_name, data[0]) if data else None

    return None


def _fetch_author_profile(user_id):
    return _fetch_profile("authors", user_id)


def _fetch_user_profile(user_id):
    return _fetch_profile("users", user_id)


def _get_authenticated_user_id(authorization: Optional[str]):
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")

    token = authorization.replace("Bearer ", "")
    response = supabase.auth.get_user(token)
    user = _extract_response_user(response)
    user_id = getattr(user, "id", None) if user is not None else None

    if isinstance(user, dict):
        user_id = user.get("id")

    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return user_id


def _get_account_profile(user_id: str):
    author_profile = _fetch_author_profile(user_id)
    if author_profile:
        return "author", "authors", author_profile

    user_profile = _fetch_user_profile(user_id)
    if user_profile:
        return "user", "users", user_profile

    raise HTTPException(status_code=404, detail="No profile row found for this account")


def _insert_profile_with_admin(table_name: str, payload: dict):
    """
    Insert profile rows with service-role privileges to bypass RLS.
    """
    return admin_supabase.table(table_name).insert(payload).execute()


def _delete_profile_with_admin(table_name: str, user_id: str):
    """
    Remove a profile row from the opposite account table when a route must be exclusive.
    """
    return admin_supabase.table(table_name).delete().eq("user_id", user_id).execute()


def _extract_response_data(response):
    if hasattr(response, "data"):
        return response.data or []

    if isinstance(response, dict):
        return response.get("data") or []

    return []


def _validate_account_type(registration: RegisterRequest, expected_account_type: str):
    if registration.account_type and registration.account_type != expected_account_type:
        raise HTTPException(
            status_code=400,
            detail=f"Use the {expected_account_type} registration endpoint for this account type"
        )


def _register_and_insert_profile(
    registration: RegisterRequest,
    profile_table: str,
    remove_profile_table: Optional[str] = None,
):
    if registration.password != registration.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")

    response = supabase.auth.sign_up({
        "email": registration.email,
        "password": registration.password
    })

    user_id = _extract_user_id(response)
    if not user_id:
        raise HTTPException(status_code=500, detail="Failed to create auth user")

    if remove_profile_table:
        _delete_profile_with_admin(remove_profile_table, user_id)

    profile_insert = _insert_profile_with_admin(profile_table, {
        "user_id": user_id,
        "name": registration.name,
        "phone": registration.phone,
        "email": registration.email,
        "created_at": datetime.now(timezone.utc).isoformat()
    })
    profile_data = _extract_response_data(profile_insert)

    if remove_profile_table:
        _delete_profile_with_admin(remove_profile_table, user_id)

    if not profile_data:
        profile_check = (
            admin_supabase
            .table(profile_table)
            .select(_profile_select_for_table(profile_table))
            .eq("user_id", user_id)
            .execute()
        )
        profile_data = _extract_response_data(profile_check)
        profile_data = [_normalize_profile(profile_table, profile) for profile in profile_data]

    if not profile_data:
        raise HTTPException(
            status_code=500,
            detail=f"Auth user was created, but profile insert into {profile_table} did not return a row"
        )

    return response, profile_data


def _register_author(author: RegisterRequest):
    _validate_account_type(author, "author")
    return _register_and_insert_profile(author, "authors")


def _register_user(user: RegisterRequest):
    _validate_account_type(user, "user")
    return _register_and_insert_profile(user, "users", remove_profile_table="authors")


# -----------------------------------
# REGISTER AUTHOR
# -----------------------------------


@author_router.post("/register")
def register_author(author: RegisterRequest):
    try:
        response, author_profile = _register_author(author)

        return {
            "message": "Registration successful",
            "user": _extract_response_user(response),
            "author_profile": author_profile
        }

    except Exception as e:
        print("REGISTER ERROR:", e)
        raise HTTPException(status_code=400, detail=str(e))


# -----------------------------------
# LOGIN AUTHOR
# -----------------------------------


@author_router.post("/login")
def login_author(author: LoginRequest):
    try:
        response = supabase.auth.sign_in_with_password({
            "email": author.email,
            "password": author.password
        })

        user = _extract_response_user(response)
        user_id = _extract_user_id(response)

        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid email or password")

        author_profile = _fetch_author_profile(user_id)
        if not author_profile:
            raise HTTPException(status_code=403, detail="This account is not registered as an author")

        return {
            "message": "Login successful",
            "session": _extract_session(response),
            "author": author_profile,
            "user": user
        }

    except Exception as e:
        print("LOGIN ERROR:", e)
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=401, detail="Invalid email or password")

# -----------------------------------
# REGISTER
# -----------------------------------


@router.post("/register")
def register(user: RegisterRequest):
    try:
        response, user_profile = _register_user(user)

        return {
            "message": "Registration successful",
            "user": _extract_response_user(response),
            "user_profile": user_profile
        }

    except Exception as e:
        print("REGISTER ERROR:", e)
        raise HTTPException(status_code=400, detail=str(e))


# -----------------------------------
# CURRENT PROFILE
# -----------------------------------


@router.get("/profile")
def get_current_profile(authorization: Optional[str] = Header(None)):
    try:
        user_id = _get_authenticated_user_id(authorization)
        account_type, _, profile = _get_account_profile(user_id)

        return {
            "message": "Profile retrieved successfully",
            "account_type": account_type,
            "profile": profile,
        }

    except HTTPException:
        raise
    except Exception as e:
        print("GET PROFILE ERROR:", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/profile/avatar")
async def upload_profile_avatar(
    file: UploadFile = File(...),
    authorization: Optional[str] = Header(None)
):
    try:
        user_id = _get_authenticated_user_id(authorization)
        account_type, table_name, _ = _get_account_profile(user_id)

        if not file.content_type or not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Profile image must be an image file")

        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Profile image is empty")

        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
            suffix = ".jpg"

        storage_path = f"{table_name}/{user_id}/{uuid4().hex}{suffix}"
        storage = admin_supabase.storage.from_(PROFILE_BUCKET)
        storage.upload(
            storage_path,
            content,
            file_options={"content-type": file.content_type}
        )

        public_url_response = storage.get_public_url(storage_path)
        public_url = (
            public_url_response.get("publicUrl")
            if isinstance(public_url_response, dict)
            else public_url_response
        )

        if not public_url:
            raise HTTPException(status_code=500, detail="Failed to create public profile image URL")

        update_response = (
            admin_supabase
            .table(table_name)
            .update({"profile_url": public_url})
            .eq("user_id", user_id)
            .execute()
        )
        updated_profile = _extract_response_data(update_response)

        if not updated_profile:
            updated_profile = [_fetch_profile(table_name, user_id)]
        else:
            updated_profile = [_normalize_profile(table_name, profile) for profile in updated_profile]

        return {
            "message": "Profile image uploaded successfully",
            "account_type": account_type,
            "profile_url": public_url,
            "avatar_url": public_url,
            "profile": updated_profile[0],
        }

    except HTTPException:
        raise
    except Exception as e:
        print("UPLOAD PROFILE AVATAR ERROR:", e)
        raise HTTPException(status_code=400, detail=str(e))


# -----------------------------------
# LOGIN
# -----------------------------------


@router.post("/login")
def login(user: LoginRequest):
    try:
        response = supabase.auth.sign_in_with_password({
            "email": user.email,
            "password": user.password
        })

        user_id = _extract_user_id(response)
        user_profile = _fetch_user_profile(user_id) if user_id else None

        return {
            "message": "Login successful",
            "session": _extract_session(response),
            "user": _extract_response_user(response),
            "user_profile": user_profile,
        }

    except Exception as e:
        print("LOGIN ERROR:", e)
        raise HTTPException(status_code=401, detail="Invalid email or password")
