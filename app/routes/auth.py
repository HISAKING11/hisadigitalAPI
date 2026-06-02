from fastapi import APIRouter, HTTPException
from app.database import supabase, admin_supabase
from app.models.auth_models import RegisterRequest, LoginRequest
from datetime import datetime, timezone
from typing import Optional


router = APIRouter(
    prefix="/rdzd/auth",
    tags=["Auth"]
)

author_router = APIRouter(
    prefix="/rdzd/auth/author",
    tags=["Author Auth"]
)


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


def _fetch_author_profile(user_id):
    result = supabase.table("authors").select("id, user_id, name, phone, email").eq("user_id", user_id).execute()

    if hasattr(result, "data"):
        return result.data[0] if result.data else None

    if isinstance(result, dict):
        data = result.get("data") or []
        return data[0] if data else None

    return None


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
            .select("id, user_id, name, phone, email")
            .eq("user_id", user_id)
            .execute()
        )
        profile_data = _extract_response_data(profile_check)

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
# LOGIN
# -----------------------------------


@router.post("/login")
def login(user: LoginRequest):
    try:
        response = supabase.auth.sign_in_with_password({
            "email": user.email,
            "password": user.password
        })

        return {
            "message": "Login successful",
            "session": _extract_session(response),
            "user": _extract_response_user(response)
        }

    except Exception as e:
        print("LOGIN ERROR:", e)
        raise HTTPException(status_code=401, detail="Invalid email or password")
