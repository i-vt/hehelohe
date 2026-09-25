import textwrap

import trio

from hehelohe.config import load_config
from hehelohe.registry import (
    discover_builtin,
    discover_modules,
    error_result,
    filter_modules,
    normalize_result,
    register,
)


def make_config():
    return load_config(config_path="/nonexistent/nope.toml")


def test_builtin_discovery_finds_all_modules():
    specs = discover_builtin(make_config())
    assert len(specs) >= 120
    # spot-check a few well-known modules and their domains
    assert specs["instagram"].domain == "instagram.com"
    assert specs["facebook"].domain == "facebook.com"
    assert specs["duolingo"].domain == "duolingo.com"
    assert specs["instagram"].category == "social_media"
    assert all(spec.legacy for spec in specs.values())


def test_password_recovery_filter():
    specs = discover_builtin(make_config())
    filtered = filter_modules(
        specs, no_password_recovery=True,
        password_recovery_names=["adobe", "mail_ru", "odnoklassniki", "samsung"],
    )
    for name in ("adobe", "mail_ru", "odnoklassniki", "samsung"):
        assert name not in filtered
    assert "instagram" in filtered


def test_include_exclude_filter():
    specs = discover_builtin(make_config())
    only = filter_modules(specs, include=["github", "twitter.com"])
    assert set(only) == {"github", "twitter"}
    rest = filter_modules(specs, exclude=["github"])
    assert "github" not in rest and "twitter" in rest


def test_normalize_result_fills_missing_keys():
    result = normalize_result({"exists": True}, "x", "x.com")
    assert result["exists"] is True
    assert result["rateLimit"] is False
    assert result["error"] is False
    assert result["name"] == "x"
    assert result["domain"] == "x.com"
    assert "others" in result and "emailrecovery" in result


def test_new_style_decorator_module(tmp_path):
    plugin = tmp_path / "mysite.py"
    plugin.write_text(textwrap.dedent("""
        from hehelohe import register

        @register(name="mysite", domain="mysite.com", category="custom")
        async def mysite(email, client):
            return {"exists": True}
    """))
    config = make_config()
    specs = discover_modules(config, extra_plugin_dirs=[str(tmp_path)])
    assert "mysite" in specs
    spec = specs["mysite"]
    assert not spec.legacy
    result = trio.run(spec.func, "a@b.c", None)
    assert result["exists"] is True
    assert result["domain"] == "mysite.com"
    assert result["rateLimit"] is False


def test_classic_style_plugin_file(tmp_path):
    plugin = tmp_path / "oldstyle.py"
    plugin.write_text(textwrap.dedent("""
        async def oldstyle(email, client, out):
            out.append({"name": "oldstyle", "domain": "old.io",
                        "exists": False, "rateLimit": False,
                        "method": "register", "frequent_rate_limit": False,
                        "emailrecovery": None, "phoneNumber": None,
                        "others": None})
    """))
    specs = discover_modules(make_config(), extra_plugin_dirs=[str(tmp_path)])
    assert "oldstyle" in specs
    result = trio.run(specs["oldstyle"].func, "a@b.c", None)
    assert result["domain"] == "old.io"
    assert result["error"] is False


def test_legacy_silent_drop_becomes_error_result():
    async def silent(email, client, out):
        return None  # appends nothing, like the old instagram bug

    from hehelohe.registry import _wrap_legacy
    spec = _wrap_legacy(silent, "silent", "silent.io", "test", "test")
    result = trio.run(spec.func, "a@b.c", None)
    assert result["error"] is True
    assert result["name"] == "silent"
    # guaranteed keys keep CSV export safe
    assert "method" in result and "frequent_rate_limit" in result


def test_legacy_exception_becomes_error_result():
    async def boom(email, client, out):
        raise RuntimeError("kaput")

    from hehelohe.registry import _wrap_legacy
    spec = _wrap_legacy(boom, "boom", "boom.io", "test", "test")
    result = trio.run(spec.func, "a@b.c", None)
    assert result["error"] is True
    assert result["domain"] == "boom.io"


def test_plugin_overrides_builtin(tmp_path):
    plugin = tmp_path / "github.py"
    plugin.write_text(textwrap.dedent("""
        from hehelohe import register

        @register(name="github", domain="github.example.com")
        async def github(email, client):
            return {"exists": False}
    """))
    specs = discover_modules(make_config(), extra_plugin_dirs=[str(tmp_path)])
    assert specs["github"].domain == "github.example.com"
    assert not specs["github"].legacy


def test_error_result_shape():
    result = error_result("n", "d.io", message="oops")
    assert result["error"] is True
    assert result["others"] == {"Message": "oops"}
    assert set(result) >= {"name", "domain", "method", "frequent_rate_limit",
                           "rateLimit", "exists", "emailrecovery",
                           "phoneNumber", "others", "error"}
