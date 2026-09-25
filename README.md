# hehelohe

**hehelohe** checks if an email address is attached to an account on 120+
sites (twitter, instagram, snapchat, imgur and more) and retrieves
information from sites that leak data through their forgotten-password flow.

It is a rebranded, hardened reboot of the holehe codebase with the
community's reported bugs fixed and new plumbing for serious use:

* ✅ **Bug-fix pass** over every actionable issue/PR filed against the
  original repo (crash on startup, CSV export crash, snapchat `IndexError`,
  imgur false-positives, instagram silent drops, mail.ru format strings,
  Python 3.13 `cgi` removal, broken Docker build, …)
* 🏠 **Residential proxy support** — proxy lists, files, gateway configs
  with sticky/rotating sessions, dead-proxy benching
* 🔁 **Retries with exponential backoff + jitter**, plus a slow second pass
  that re-checks rate-limited sites
* ⚙️ **One TOML config file** holding every tunable — no more magic numbers
  buried in the code
* 🧩 **A real plugin system** — drop a decorated function in a folder and it
  runs; no core edits, no giant dict to maintain
* 🚦 **Bounded concurrency** so the first wave of requests doesn't trigger
  the very rate-limits you're trying to avoid

## Installation

```bash
git clone https://github.com/i-vt/hehelohe.git
cd hehelohe/
pip install .
```

### With Docker

```bash
docker build . -t hehelohe
docker run hehelohe test@gmail.com
# with your own proxies / config mounted in:
docker run -v "$PWD/hehelohe.toml:/data/hehelohe.toml" hehelohe --config /data/hehelohe.toml test@gmail.com
```

## Usage

```bash
hehelohe test@gmail.com
hehelohe first@a.com second@b.org          # several emails in one run
hehelohe --only-used --no-color test@gmail.com
hehelohe -C test@gmail.com                 # export results to CSV
hehelohe --include twitter,instagram,github test@gmail.com
hehelohe --exclude adobe,samsung test@gmail.com
hehelohe --list-modules                    # show everything that would run
```

### Proxies

```bash
# single proxy
hehelohe --proxy http://user:pass@1.2.3.4:8080 test@gmail.com

# pool from a file, random rotation (socks5 works too)
hehelohe --proxy-file proxies.txt --proxy-rotation random test@gmail.com
```

Residential gateway providers go in the config file — including the common
"session-in-username" sticky/rotating session pattern:

```toml
[proxy.residential]
enabled = true
host = "gate.provider.com"
port = 7000
username = "customer-username-session-{session}"
password = "secret"
session_per_module = true   # new exit IP for every site checked
```

### Retries & backoff

Out of the box each site gets up to 2 retries with exponential backoff
(`base * factor**attempt`, capped, plus jitter) and rate-limited sites are
re-checked once at the end with low concurrency. Everything is tunable:

```toml
[retry]
max_retries = 3
backoff_base = 2.0
backoff_factor = 2.0
backoff_max = 60.0
backoff_jitter = 1.0
```

### Configuration

Every default lives in [`hehelohe/defaults.toml`](hehelohe/defaults.toml).
Override any of it via `./hehelohe.toml`, `~/.config/hehelohe/hehelohe.toml`
or `--config my.toml` — see [`hehelohe.toml.example`](hehelohe.toml.example).
CLI flags always win.

### Writing your own modules

See [docs/EXTENDING.md](docs/EXTENDING.md) — it's one decorated function:

```python
from hehelohe import register

@register(name="mysite", domain="mysite.com")
async def mysite(email, client):
    r = await client.get(f"https://mysite.com/api?mail={email}")
    return {"exists": "taken" in r.text, "rateLimit": r.status_code == 429}
```

Drop it in `~/.config/hehelohe/plugins/` and it shows up in
`hehelohe --list-modules`. Classic holehe-style modules work unmodified.

## Result legend

`[+] Email used`, `[-] Email not used`, `[x] Rate limit`, `[!] Error`

## Disclaimer

For OSINT and lawful security research on addresses you own or are
authorized to test. You are responsible for complying with each site's
terms of service.

## License

GPL-3.0 — maintained by [i-vt](https://github.com/i-vt) at
[i-vt/hehelohe](https://github.com/i-vt/hehelohe). See [LICENSE.md](LICENSE.md).
