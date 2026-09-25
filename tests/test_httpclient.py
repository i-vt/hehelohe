import random

from hehelohe.config import load_config
from hehelohe.httpclient import (
    ProxyPool,
    backoff_delay,
    build_residential_url,
    proxies_from_config,
)


def make_config():
    return load_config(config_path="/nonexistent/nope.toml")


def test_backoff_grows_and_is_capped():
    config = make_config()
    random.seed(1)
    d0 = backoff_delay(0, config)
    d1 = backoff_delay(1, config)
    d2 = backoff_delay(2, config)
    assert d0 >= 1.0 and d1 >= 2.0 and d2 >= 4.0       # base * factor**n
    assert backoff_delay(99, config) <= 30.0 + 0.5     # cap + max jitter


def test_backoff_respects_config():
    config = make_config()
    config["retry"]["backoff_base"] = 5.0
    config["retry"]["backoff_jitter"] = 0.0
    assert backoff_delay(0, config) == 5.0
    assert backoff_delay(2, config) == 20.0


def test_round_robin_rotation():
    pool = ProxyPool(["http://a:1", "http://b:2"], rotation="round-robin")
    picks = [pool.acquire() for _ in range(4)]
    assert picks == ["http://a:1", "http://b:2", "http://a:1", "http://b:2"]


def test_dead_proxy_is_benched():
    pool = ProxyPool(["http://a:1", "http://b:2"], max_failures=2)
    pool.report_failure("http://a:1")
    pool.report_failure("http://a:1")
    for _ in range(5):
        assert pool.acquire() == "http://b:2"
    pool.report_failure("http://b:2")
    pool.report_failure("http://b:2")
    assert pool.acquire() is None          # everything benched -> direct
    assert not pool


def test_success_resets_failure_count():
    pool = ProxyPool(["http://a:1"], max_failures=2)
    pool.report_failure("http://a:1")
    pool.report_success("http://a:1")
    pool.report_failure("http://a:1")
    assert pool.acquire() == "http://a:1"  # not benched yet


def test_residential_url_with_session_placeholder():
    res_cfg = {
        "enabled": True, "protocol": "http", "host": "gate.example.com",
        "port": 7000, "username": "cust-session-{session}",
        "password": "pw", "session_length": 10,
    }
    url1 = build_residential_url(res_cfg)
    url2 = build_residential_url(res_cfg)
    assert url1.startswith("http://cust-session-")
    assert url1.endswith(":pw@gate.example.com:7000")
    assert "{session}" not in url1
    assert url1 != url2                     # fresh session each call
    sticky = build_residential_url(res_cfg, session="abc")
    assert sticky == "http://cust-session-abc:pw@gate.example.com:7000"


def test_session_per_module_materializes_fresh_urls():
    res_cfg = {
        "enabled": True, "protocol": "http", "host": "gate.example.com",
        "port": 7000, "username": "cust-{session}", "password": "pw",
        "session_per_module": True,
    }
    pool = ProxyPool([], res_cfg=res_cfg)
    first, second = pool.acquire(), pool.acquire()
    assert first != second
    # failure tracking maps materialized URLs back to the template
    pool.report_failure(first)
    pool.report_failure(second)
    pool.report_failure(build_residential_url(res_cfg))
    assert not pool                          # residential template benched


def test_proxies_from_config_disabled_by_default():
    proxies, res_cfg = proxies_from_config(make_config())
    assert proxies == [] and res_cfg is None


def test_proxies_from_config_filters_bad_schemes(capsys):
    config = make_config()
    config["proxy"]["enabled"] = True
    config["proxy"]["proxies"] = ["http://ok:1", "ftp://bad:2"]
    proxies, _ = proxies_from_config(config)
    assert proxies == ["http://ok:1"]
