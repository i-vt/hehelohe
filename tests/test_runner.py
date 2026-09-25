import trio

from hehelohe.config import load_config
from hehelohe.httpclient import ClientPool
from hehelohe.registry import ModuleSpec, normalize_result
from hehelohe.runner import run_scan, run_single


class NullProgress:
    total = 0

    def update(self, n=1):
        pass

    def refresh(self):
        pass


def make_config(**retry_overrides):
    config = load_config(config_path="/nonexistent/nope.toml")
    config["retry"].update(
        max_retries=2, backoff_base=0.0, backoff_jitter=0.0,
        second_pass_delay=0.0,
    )
    config["retry"].update(retry_overrides)
    return config


def make_spec(name, behavior):
    """behavior: list of dicts returned on successive attempts."""
    calls = {"n": 0}

    async def func(email, client):
        step = behavior[min(calls["n"], len(behavior) - 1)]
        calls["n"] += 1
        return normalize_result(step, name, f"{name}.io")

    spec = ModuleSpec(name=name, domain=f"{name}.io", func=func)
    spec.calls = calls
    return spec


def run(coro, *args):
    return trio.run(coro, *args)


def test_retry_on_rate_limit_then_success():
    config = make_config()
    pool = ClientPool(timeout=5, concurrency=2)
    spec = make_spec("flaky", [{"rateLimit": True}, {"exists": True}])
    result = run(run_single, spec, "a@b.c", pool, config)
    assert result["exists"] is True
    assert spec.calls["n"] == 2


def test_retry_gives_up_after_max_retries():
    config = make_config(max_retries=1)
    pool = ClientPool(timeout=5, concurrency=2)
    spec = make_spec("stuck", [{"rateLimit": True}])
    result = run(run_single, spec, "a@b.c", pool, config)
    assert result["rateLimit"] is True
    assert spec.calls["n"] == 2  # 1 initial + 1 retry


def test_retry_on_error():
    config = make_config()
    pool = ClientPool(timeout=5, concurrency=2)
    spec = make_spec("erratic", [{"error": True}, {"exists": False}])
    result = run(run_single, spec, "a@b.c", pool, config)
    assert result["error"] is False
    assert spec.calls["n"] == 2


def test_no_retry_when_disabled():
    config = make_config(retry_on_rate_limit=False, retry_on_error=False)
    pool = ClientPool(timeout=5, concurrency=2)
    spec = make_spec("once", [{"rateLimit": True}])
    run(run_single, spec, "a@b.c", pool, config)
    assert spec.calls["n"] == 1


def test_second_pass_recovers_rate_limited():
    config = make_config(max_retries=0, second_pass=True,
                         second_pass_concurrency=1)
    pool = ClientPool(timeout=5, concurrency=2)
    good = make_spec("good", [{"exists": True}])
    flaky = make_spec("flaky", [{"rateLimit": True}, {"exists": True}])
    results = run(run_scan, [good, flaky], "a@b.c", pool, config,
                  NullProgress())
    by_name = {r["name"]: r for r in results}
    assert by_name["good"]["exists"] is True
    assert by_name["flaky"]["exists"] is True     # recovered on 2nd pass
    assert flaky.calls["n"] == 2


def test_second_pass_disabled():
    config = make_config(max_retries=0, second_pass=False)
    pool = ClientPool(timeout=5, concurrency=2)
    flaky = make_spec("flaky", [{"rateLimit": True}, {"exists": True}])
    results = run(run_scan, [flaky], "a@b.c", pool, config, NullProgress())
    assert results[0]["rateLimit"] is True
    assert flaky.calls["n"] == 1


def test_results_are_sorted_and_complete():
    config = make_config(max_retries=0, second_pass=False)
    pool = ClientPool(timeout=5, concurrency=4)
    specs = [make_spec(name, [{"exists": False}])
             for name in ("zeta", "alpha", "mid")]
    results = run(run_scan, specs, "a@b.c", pool, config, NullProgress())
    assert [r["name"] for r in results] == ["alpha", "mid", "zeta"]
    for result in results:
        assert {"name", "domain", "method", "frequent_rate_limit",
                "rateLimit", "exists", "emailrecovery", "phoneNumber",
                "others", "error"} <= set(result)
