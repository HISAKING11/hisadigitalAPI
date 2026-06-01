import json
from typing import Any, Dict
from urllib import request, error


EMAILJS_SEND_URL = "https://api.emailjs.com/api/v1.0/email/send"


def send_emailjs_template(
    service_id: str,
    template_id: str,
    template_params: Dict[str, Any],
    public_key: str,
    private_key: str | None = None,
) -> Dict[str, Any]:
    payload = {
        "service_id": service_id,
        "template_id": template_id,
        "user_id": public_key,
        "template_params": template_params,
    }
    if private_key:
        payload["accessToken"] = private_key

    req = request.Request(
        EMAILJS_SEND_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "HisaDigitalOrderAPI/1.0",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return {
                "status": response.status,
                "body": raw,
            }
    except error.HTTPError as exc:
        error_body = exc.read().decode("utf-8") if exc.fp else str(exc)
        raise RuntimeError(f"EmailJS request failed: {error_body}") from exc
    except Exception as exc:
        raise RuntimeError(f"EmailJS request failed: {exc}") from exc
