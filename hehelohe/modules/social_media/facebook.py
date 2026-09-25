from hehelohe.core import *
from hehelohe.localuseragent import *


async def facebook(email, client, out):
    name = "facebook"
    domain = "facebook.com"
    method = "register"
    frequent_rate_limit = True

    def result(rate_limit, exists):
        out.append({"name": name, "domain": domain, "method": method,
                    "frequent_rate_limit": frequent_rate_limit,
                    "rateLimit": rate_limit,
                    "exists": exists,
                    "emailrecovery": None,
                    "phoneNumber": None,
                    "others": None})

    headers = {
        'User-Agent': random.choice(ua["browsers"]["chrome"]),
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.5',
        'Origin': 'https://www.facebook.com',
        'DNT': '1',
        'Connection': 'keep-alive',
    }

    try:
        response = await client.get(
            "https://www.facebook.com/accounts/emailsignup/", headers=headers)
        if response.status_code == 404:
            raise ValueError("endpoint not found")
        token = response.text.split('{"config":{"csrf_token":"')[1].split('"')[0]
    except Exception:
        result(True, False)
        return None

    data = {
        'email': email,
        'username': ''.join(random.choice(string.ascii_lowercase + string.digits)
                            for i in range(random.randint(6, 30))),
        'first_name': '',
        'opt_into_one_tap': 'false'
    }
    headers["x-csrftoken"] = token

    try:
        check = await client.post(
            "https://www.facebook.com/api/v1/web/accounts/web_create_ajax/attempt/",
            data=data,
            headers=headers)
        check = check.json()
    except Exception:
        result(True, False)
        return None

    if check.get("status") == "fail":
        result(True, False)
        return None

    errors = check.get("errors") or {}
    email_errors = errors.get("email")
    if email_errors:
        first = email_errors[0] if isinstance(email_errors, list) and email_errors else {}
        if first.get("code") == "email_is_taken" or "email_sharing_limit" in str(errors):
            result(False, True)
        else:
            # Unknown email error payload: cannot conclude, report rate limit
            # instead of silently dropping the module (silent-drop fix).
            result(True, False)
    else:
        result(False, False)
