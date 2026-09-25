"""Concurrent scan orchestration with retries and exponential backoff."""

import time

import trio

from hehelohe.httpclient import backoff_delay
from hehelohe.registry import error_result

#: Exceptions that mean "this proxy/connection is broken" -- the proxy pool
#: is told about them so dead proxies get benched.
PROXY_FAILURE_EXCEPTIONS = (
    trio.BrokenResourceError,
    trio.ClosedResourceError,
    trio.TooSlowError,
    OSError,
)


async def run_single(spec, email, client_pool, config):
    """Run one site check with retries and exponential backoff.

    Retry policy (all values from the config file):
      * up to ``retry.max_retries`` extra attempts
      * delay = min(backoff_base * backoff_factor**attempt, backoff_max)
        plus up to ``backoff_jitter`` seconds of random jitter
      * a fresh proxy is picked for every attempt when proxies are enabled
    """
    retry_cfg = config["retry"]
    max_retries = int(retry_cfg["max_retries"])
    retry_on_rate_limit = bool(retry_cfg["retry_on_rate_limit"])
    retry_on_error = bool(retry_cfg["retry_on_error"])

    last_result = error_result(spec.name, spec.domain, spec.method,
                               spec.frequent_rate_limit)

    for attempt in range(max_retries + 1):
        client, proxy = await client_pool.acquire()
        try:
            result = await spec.func(email, client)
            client_pool.proxy_pool.report_success(proxy)
        except Exception as exc:
            # Should not happen (modules are wrapped), but never let one
            # site kill the whole scan.
            client_pool.proxy_pool.report_failure(proxy)
            result = error_result(spec.name, spec.domain, spec.method,
                                  spec.frequent_rate_limit,
                                  message=str(exc) or None)
        finally:
            client_pool.release(proxy)

        last_result = result

        should_retry = attempt < max_retries and (
            (result["rateLimit"] and retry_on_rate_limit)
            or (result["error"] and retry_on_error)
        )
        if not should_retry:
            break
        await trio.sleep(backoff_delay(attempt, config))

    return last_result


async def run_pass(specs, email, client_pool, config, concurrency, progress):
    """Run one pass over the given specs; returns {name: result}."""
    results = {}
    limiter = trio.CapacityLimiter(max(1, int(concurrency)))

    async def worker(spec):
        async with limiter:
            results[spec.name] = await run_single(spec, email, client_pool,
                                                  config)
            progress.update(1)

    async with trio.open_nursery() as nursery:
        for spec in specs:
            nursery.start_soon(worker, spec)

    return results


async def run_scan(specs, email, client_pool, config, progress):
    """Full scan: main pass + optional slow second pass for rate-limits.

    The second pass re-checks sites that are still rate-limited after the
    main pass, once, with low concurrency -- many "rate limits" are just
    bursts caused by the first wave of parallel requests.
    """
    specs = list(specs)
    results = await run_pass(specs, email, client_pool, config,
                             config["core"]["concurrency"], progress)

    retry_cfg = config["retry"]
    if retry_cfg.get("second_pass", True):
        retry_specs = [spec for spec in specs
                       if results[spec.name]["rateLimit"]]
        if retry_specs:
            delay = float(retry_cfg.get("second_pass_delay", 5.0))
            if delay > 0:
                await trio.sleep(delay)
            progress.total = (progress.total or 0) + len(retry_specs)
            progress.refresh()
            refreshed = await run_pass(
                retry_specs, email, client_pool, config,
                retry_cfg.get("second_pass_concurrency", 3), progress,
            )
            results.update(refreshed)

    return [results[name] for name in sorted(results)]
