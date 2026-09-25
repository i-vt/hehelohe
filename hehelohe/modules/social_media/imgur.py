from hehelohe.core import *
from hehelohe.localuseragent import *


def _is_captcha_error(value):
    """Recursively look for captcha markers in API error payloads."""
    if isinstance(value, str):
        return "captcha" in value.lower()
    if isinstance(value, dict):
        error_keys = {
            "error", "errors", "error_message", "errormessage",
            "message", "messages",
        }
        return any(
            _is_captcha_error(item)
            for key, item in value.items()
            if str(key).lower() in error_keys
        )
    if isinstance(value, (list, tuple)):
        return any(_is_captcha_error(item) for item in value)
    return False


def _has_unsuccessful_status(payload):
    if not isinstance(payload, dict):
        return False
    status = payload.get("status")
    return payload.get("success") is False or (
        isinstance(status, int) and 400 <= status < 600
    )


async def imgur(email, client, out):
    name = "imgur"
    domain = "imgur.com"
    method = "register"
    frequent_rate_limit = True

    def result(rate_limit, exists):
        return {
            "name": name,
            "domain": domain,
            "method": method,
            "frequent_rate_limit": frequent_rate_limit,
            "rateLimit": rate_limit,
            "exists": exists,
            "emailrecovery": None,
            "phoneNumber": None,
            "others": None,
        }

    headers = {
        "User-Agent": random.choice(ua["browsers"]["chrome"]),
        "Accept": "*/*",
        "Accept-Language": "en,en-US;q=0.5",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": "https://imgur.com",
        "DNT": "1",
        "Connection": "keep-alive",
        "TE": "Trailers",
    }

    await client.get("https://imgur.com/register?redirect=%2Fuser", headers=headers)

    headers["X-Requested-With"] = "XMLHttpRequest"

    response = await client.post(
        "https://imgur.com/signin/ajax_email_available",
        headers=headers,
        data={"email": email},
    )
    if response.status_code != 200:
        out.append(result(True, False))
        return

    try:
        payload = response.json()
    except ValueError:
        out.append(result(True, False))
        return

    body = payload.get("data", {}) if isinstance(payload, dict) else {}
    available = body.get("available") if isinstance(body, dict) else None

    # "Invalid email domain" means the address can not register -> not used.
    if "Invalid email domain" in response.text:
        out.append(result(False, False))
    # Anything that is not a clean boolean answer (captcha, error status,
    # missing field) must not be reported as "account exists" (fixes the
    # always-true false positives).
    elif (
        _has_unsuccessful_status(payload)
        or _is_captcha_error(payload)
        or not isinstance(available, bool)
    ):
        out.append(result(True, False))
    elif available:
        out.append(result(False, False))
    else:
        out.append(result(False, True))
