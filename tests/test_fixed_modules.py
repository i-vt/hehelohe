"""Regression tests for the bug-fix pass over the original holehe issues."""

import httpx
import trio

from hehelohe.modules.social_media.imgur import imgur
from hehelohe.modules.social_media.snapchat import snapchat


class FakeClient:
    """Minimal stand-in for httpx.AsyncClient used by modules."""

    def __init__(self, get_response=None, post_response=None):
        self._get = get_response
        self._post = post_response

    async def get(self, *args, **kwargs):
        return self._get

    async def post(self, *args, **kwargs):
        return self._post


def run_module(module, client):
    out = []
    trio.run(module, "user@example.com", client, out)
    return out


# --- imgur: captcha/error payloads must not be false positives (issue #207)

def test_imgur_captcha_is_rate_limited_not_registered():
    response = httpx.Response(
        200, json={"data": {"available": False},
                   "errors": ["A captcha token is required."]})
    out = run_module(imgur, FakeClient(httpx.Response(200), response))
    assert out[0]["rateLimit"] is True
    assert out[0]["exists"] is False


def test_imgur_missing_availability_is_rate_limited():
    response = httpx.Response(200, json={"data": {"error": "captcha-required"}})
    out = run_module(imgur, FakeClient(httpx.Response(200), response))
    assert out[0]["rateLimit"] is True
    assert out[0]["exists"] is False


def test_imgur_available_email():
    response = httpx.Response(200, json={"data": {"available": True}})
    out = run_module(imgur, FakeClient(httpx.Response(200), response))
    assert out[0]["rateLimit"] is False and out[0]["exists"] is False


def test_imgur_taken_email():
    response = httpx.Response(200, json={"data": {"available": False}})
    out = run_module(imgur, FakeClient(httpx.Response(200), response))
    assert out[0]["rateLimit"] is False and out[0]["exists"] is True


# --- snapchat: missing login tokens must not raise IndexError (issue #228)

def test_snapchat_missing_tokens_does_not_crash():
    page = httpx.Response(200, text="<html>no tokens here</html>")
    out = run_module(snapchat, FakeClient(page))
    assert len(out) == 1
    assert out[0]["rateLimit"] is True
    assert out[0]["exists"] is False


def test_snapchat_tokens_present():
    page = httpx.Response(
        200, text='data-xsrf="TOKEN123" data-web-client-id="CLIENT42"')
    answer = httpx.Response(200, json={"hasSnapchat": True})
    out = run_module(snapchat, FakeClient(page, answer))
    assert out[0]["exists"] is True


# --- facebook: must not import requests (crashed the whole tool at startup)

def test_facebook_module_has_no_requests_import():
    import inspect

    import hehelohe.modules.social_media.facebook as fb
    source = inspect.getsource(fb)
    assert "import requests" not in source
    assert fb.facebook.__name__ == "facebook"


# --- mail_ru: f-string interpolation actually sends the email (PR #289)

def test_mail_ru_sends_interpolated_email():
    import hehelohe.modules.mails.mail_ru as mail_ru_mod

    captured = {}

    class CaptureClient:
        async def post(self, url, headers=None, data=None):
            captured["headers"] = headers
            captured["data"] = data
            return httpx.Response(
                200, json={"status": 200, "body": {"phones": [], "emails": []}})

    out = []
    trio.run(mail_ru_mod.mail_ru, "target@example.com", CaptureClient(), out)
    assert "target@example.com" in captured["headers"]["referer"]
    assert "{email}" not in captured["headers"]["referer"]
    assert captured["data"].startswith("email=target%40example.com")
    assert out[0]["exists"] is True
