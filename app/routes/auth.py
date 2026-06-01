from fastapi import APIRouter, HTTPException
from app.database import supabase
from app.models.auth_models import RegisterRequest, LoginRequest


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


def _register_author(author: RegisterRequest):
    if author.password != author.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")

    response = supabase.auth.sign_up({
        "email": author.email,
        "password": author.password
    })

    user_id = _extract_user_id(response)
    if not user_id:
        raise HTTPException(status_code=500, detail="Failed to create auth user")

    author_insert = supabase.table("authors").insert({
        "user_id": user_id,
        "name": author.name,
        "phone": author.phone,
        "email": author.email
    }).execute()

    return response, author_insert


# -----------------------------------
# REGISTER AUTHOR
# -----------------------------------


@author_router.post("/register")
def register_author(author: RegisterRequest):
    try:
        response, author_insert = _register_author(author)

        return {
            "message": "Registration successful",
            "user": _extract_response_user(response),
            "author_profile": getattr(author_insert, "data", None)
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
        response, author_insert = _register_author(user)

        return {
            "message": "Registration successful",
            "user": _extract_response_user(response),
            "author_profile": getattr(author_insert, "data", None)
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