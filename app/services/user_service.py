from app.database import supabase, admin_supabase


def update_user_profile(user_id: str, name: str, phone: str):
    data = {}
    if name is not None:
        data["name"] = name
    if phone is not None:
        data["phone"] = phone

    if not data:
        return None

    result = admin_supabase.table("users").update(data).eq("user_id", user_id).execute()

    if hasattr(result, "data") and result.data:
        return result.data[0]
    return None


def is_author(user_id: str) -> bool:
    result = admin_supabase.table("authors").select("id").eq("user_id", user_id).execute()
    if hasattr(result, "data"):
        return len(result.data) > 0
    return False


def update_auth_email(user_id: str, new_email: str):
    admin_supabase.auth.admin.update_user_by_id(user_id, {"email": new_email})
    admin_supabase.table("users").update({"email": new_email}).eq("user_id", user_id).execute()


def change_user_password(user_id: str, email: str, current_password: str, new_password: str):
    supabase.auth.sign_in_with_password({
        "email": email,
        "password": current_password,
    })
    admin_supabase.auth.admin.update_user_by_id(user_id, {"password": new_password})
