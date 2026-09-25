import os

from hehelohe.config import load_config, cfg_get, _deep_merge


def test_defaults_load():
    config = load_config(config_path="/nonexistent/nope.toml")
    assert config["core"]["timeout"] == 10
    assert config["retry"]["backoff_factor"] == 2.0
    assert config["proxy"]["enabled"] is False
    # every bundled module has a domain entry
    assert config["domains"]["facebook"] == "facebook.com"
    assert config["domains"]["duolingo"] == "duolingo.com"
    assert len(config["domains"]) >= 120


def test_user_config_overrides(tmp_path, monkeypatch):
    override = tmp_path / "hehelohe.toml"
    override.write_text(
        '[core]\ntimeout = 42\n[retry]\nmax_retries = 5\n'
        '[proxy]\nenabled = true\nproxies = ["http://u:p@1.2.3.4:8080"]\n'
    )
    monkeypatch.chdir(tmp_path)  # ./hehelohe.toml is picked up automatically
    config = load_config()
    assert config["core"]["timeout"] == 42
    assert config["retry"]["max_retries"] == 5
    # untouched values keep their defaults
    assert config["retry"]["backoff_base"] == 1.0
    assert config["proxy"]["proxies"] == ["http://u:p@1.2.3.4:8080"]


def test_explicit_config_path(tmp_path, monkeypatch):
    override = tmp_path / "custom.toml"
    override.write_text("[core]\nconcurrency = 3\n")
    monkeypatch.chdir("/")  # make sure ./hehelohe.toml is not in the way
    config = load_config(config_path=str(override))
    assert config["core"]["concurrency"] == 3


def test_deep_merge_keeps_untouched_nested_values():
    base = {"a": {"b": 1, "c": 2}}
    _deep_merge(base, {"a": {"b": 9}})
    assert base == {"a": {"b": 9, "c": 2}}


def test_cfg_get():
    config = {"x": {"y": {"z": 7}}}
    assert cfg_get(config, "x.y.z") == 7
    assert cfg_get(config, "x.y.missing", "fallback") == "fallback"
