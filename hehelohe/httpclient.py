"""HTTP client pool with (residential) proxy support and backoff helpers."""

import random
import string

import httpx

# Schemes httpx knows how to proxy (socks5 needs the httpx[socks] extra).
SUPPORTED_PROXY_SCHEMES = ("http://", "https://", "socks5://")


def backoff_delay(attempt, config):
    """Exponential backoff with jitter, all values from the config file.

    delay = min(backoff_base * backoff_factor**attempt, backoff_max)
            + uniform(0, backoff_jitter)
    """
    retry_cfg = config["retry"]
    base = float(retry_cfg["backoff_base"])
    factor = float(retry_cfg["backoff_factor"])
    cap = float(retry_cfg["backoff_max"])
    jitter = float(retry_cfg["backoff_jitter"])
    delay = min(base * (factor ** attempt), cap)
    if jitter > 0:
        delay += random.uniform(0, jitter)
    return delay


def _read_proxy_file(path):
    proxies = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith("#"):
                proxies.append(line)
    return proxies


def new_session_id(length=8):
    return "".join(random.choices(string.ascii_lowercase + string.digits,
                                  k=int(length)))


def build_residential_url(res_cfg, session=None):
    """Turn the [proxy.residential] block into a proxy URL.

    The username may contain a ``{session}`` placeholder; it is replaced by
    a random session id so residential providers that key the exit IP on the
    username ("sticky sessions") rotate IPs the way the user configured.
    """
    username = res_cfg.get("username", "")
    password = res_cfg.get("password", "")
    if "{session}" in username:
        session = session or new_session_id(res_cfg.get("session_length", 8))
        username = username.replace("{session}", session)

    auth = ""
    if username:
        auth = username
        if password:
            auth += ":" + password
        auth += "@"

    return "{protocol}://{auth}{host}:{port}".format(
        protocol=res_cfg.get("protocol", "http"),
        auth=auth,
        host=res_cfg.get("host", ""),
        port=int(res_cfg.get("port", 0)),
    )


class ProxyPool:
    """Hands out proxies round-robin or randomly, benching dead ones.

    Proxies come from three sources (all optional):
      * the inline ``[proxy].proxies`` list / ``--proxy`` flags
      * a text file (``[proxy].proxy_file`` / ``--proxy-file``)
      * the ``[proxy.residential]`` gateway block
    """

    def __init__(self, proxies, rotation="round-robin", max_failures=3,
                 res_cfg=None):
        self.rotation = rotation
        self.max_failures = int(max_failures)
        self._res_cfg = res_cfg or {}
        self._residential_template = None

        self._proxies = list(proxies)
        if self._res_cfg.get("enabled", False):
            self._residential_template = build_residential_url(self._res_cfg)
            self._proxies.append(self._residential_template)

        self._rotate_session = bool(
            self._res_cfg.get("enabled", False)
            and self._res_cfg.get("session_per_module", False)
            and "{session}" in self._res_cfg.get("username", "")
        )
        self._failures = {p: 0 for p in self._proxies}
        self._benched = set()
        self._index = 0

    def __bool__(self):
        return any(p not in self._benched for p in self._proxies)

    def __len__(self):
        return len(self._proxies)

    def acquire(self):
        """Return the next usable proxy URL, or None for a direct connection."""
        usable = [p for p in self._proxies if p not in self._benched]
        if not usable:
            return None
        if self.rotation == "random":
            proxy = random.choice(usable)
        else:  # round-robin
            proxy = usable[self._index % len(usable)]
            self._index += 1
        if proxy == self._residential_template and self._rotate_session:
            # Fresh session id -> fresh exit IP for this site check.
            return build_residential_url(self._res_cfg)
        return proxy

    def _match(self, proxy):
        """Map a (possibly session-materialized) URL back to its template."""
        if proxy in self._failures:
            return proxy
        if self._residential_template is not None:
            template_host = self._residential_template.split("@")[-1]
            if proxy.split("@")[-1] == template_host:
                return self._residential_template
        return None

    def report_failure(self, proxy):
        if proxy is None:
            return
        key = self._match(proxy)
        if key is None:
            return
        self._failures[key] += 1
        if self._failures[key] >= self.max_failures:
            self._benched.add(key)

    def report_success(self, proxy):
        if proxy is None:
            return
        key = self._match(proxy)
        if key is not None:
            self._failures[key] = 0


def proxies_from_config(config):
    """Collect the inline + file proxies from the effective configuration."""
    proxy_cfg = config["proxy"]
    if not proxy_cfg.get("enabled", False):
        return [], None

    proxies = list(proxy_cfg.get("proxies", []) or [])

    proxy_file = proxy_cfg.get("proxy_file", "")
    if proxy_file:
        proxies.extend(_read_proxy_file(proxy_file))

    valid = []
    for proxy in proxies:
        if proxy.lower().startswith(SUPPORTED_PROXY_SCHEMES):
            valid.append(proxy)
        else:
            print(f"[!] Skipping proxy with unsupported scheme: {proxy}")

    res_cfg = proxy_cfg.get("residential", {}) or {}
    if not res_cfg.get("enabled", False):
        res_cfg = None
    return valid, res_cfg


class ClientPool:
    """One httpx.AsyncClient per proxy plus one direct client.

    Residential setups with ``session_per_module`` mint a fresh proxy URL
    (fresh exit IP) for every site check, so the client cache is bounded:
    idle, least-recently-used clients are closed once the cache grows past
    ``max_cached``.
    """

    def __init__(self, timeout, concurrency, proxy_pool=None, max_cached=None):
        limits = httpx.Limits(
            max_connections=concurrency,
            max_keepalive_connections=concurrency,
        )
        self._timeout = timeout
        self._limits = limits
        self.proxy_pool = proxy_pool or ProxyPool([])
        # Enough room for every in-flight task plus the static proxies.
        self._max_cached = max_cached or (2 * concurrency + len(self.proxy_pool) + 2)
        self._clients = {}  # proxy url -> [client, in_use, tick]
        self._tick = 0
        self._get(None)  # pre-create the direct client

    def _new_client(self, proxy):
        kwargs = {
            "timeout": self._timeout,
            "limits": self._limits,
            "follow_redirects": True,
        }
        if proxy is not None:
            kwargs["proxy"] = proxy
        return httpx.AsyncClient(**kwargs)

    def _get(self, proxy):
        if proxy not in self._clients:
            self._clients[proxy] = [self._new_client(proxy), 0, 0]
        return self._clients[proxy]

    async def acquire(self):
        """Return (client, proxy_url) for the next site check."""
        proxy = self.proxy_pool.acquire() if self.proxy_pool else None
        if proxy not in self._clients and len(self._clients) >= self._max_cached:
            await self._evict_idle()
        entry = self._get(proxy)
        self._tick += 1
        entry[1] += 1      # in use
        entry[2] = self._tick
        return entry[0], proxy

    def release(self, proxy):
        entry = self._clients.get(proxy)
        if entry is not None and entry[1] > 0:
            entry[1] -= 1

    async def _evict_idle(self):
        idle = [
            (tick, proxy) for proxy, (client, in_use, tick)
            in self._clients.items()
            if in_use == 0 and proxy is not None  # never evict the direct client
        ]
        if not idle:
            return
        _, victim = min(idle)
        client, _, _ = self._clients.pop(victim)
        await client.aclose()

    async def aclose(self):
        for client, _, _ in self._clients.values():
            await client.aclose()
        self._clients.clear()
