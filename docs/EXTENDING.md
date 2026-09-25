# Extending hehelohe

hehelohe discovers site modules from three places, no core changes needed:

| Source | Where | Style |
|---|---|---|
| Built-ins | `hehelohe/modules/<category>/<name>.py` | classic |
| Plugin dirs | `~/.config/hehelohe/plugins/`, `./hehelohe_plugins/`, `--plugins-dir DIR`, or `[modules].plugin_dirs` | both |
| Pip packages | `hehelohe.modules` entry-point group | decorator |

A plugin with the same name as a built-in **overrides** it — handy for
patching a broken site without forking.

---

## New style (recommended): `@register`

Drop a file like this into `~/.config/hehelohe/plugins/mysite.py`:

```python
from hehelohe import register

@register(
    name="mysite",                    # unique module name
    domain="mysite.com",              # shown in results
    category="social",                # any label; used by --list-modules
    method="register",                # register | login | password recovery
    frequent_rate_limit=False,
)
async def mysite(email, client):
    """client is a shared httpx.AsyncClient (proxy already applied)."""
    r = await client.get(f"https://mysite.com/api/email_taken?mail={email}")
    if r.status_code == 429:
        return {"rateLimit": True}               # hehelohe retries with backoff
    data = r.json()
    return {
        "exists": data.get("taken", False),
        "others": {"FullName": data.get("name")},  # optional extra info
    }
```

That is the whole module. Every field you omit is filled with a safe
default, and exceptions are caught for you and reported as `[!] Error`.

### Result fields

| Key | Type | Meaning |
|---|---|---|
| `exists` | bool | account found for the email |
| `rateLimit` | bool | you were throttled / captcha'd (triggers retry) |
| `error` | bool | set automatically when the module crashes |
| `emailrecovery` | str / None | masked recovery email, if the site leaks one |
| `phoneNumber` | str / None | masked phone, if the site leaks one |
| `others` | dict / None | anything extra (`FullName`, `Date, time of the creation`, `Message` are printed) |

## Classic style (holehe-compatible)

Old holehe modules keep working unchanged — both in the bundled
`hehelohe/modules/` tree and in plugin directories. The file
`<name>.py` must define an async function with the same name:

```python
from hehelohe.core import *            # re, json, random, string, BeautifulSoup...
from hehelohe.localuseragent import *  # ua: rotating user-agent strings

async def mysite(email, client, out):
    name = "mysite"
    domain = "mysite.com"
    method = "register"
    frequent_rate_limit = False

    r = await client.get(f"https://mysite.com/api?mail={email}")
    out.append({
        "name": name, "domain": domain, "method": method,
        "frequent_rate_limit": frequent_rate_limit,
        "rateLimit": r.status_code == 429,
        "exists": "taken" in r.text,
        "emailrecovery": None, "phoneNumber": None, "others": None,
    })
```

The runner normalizes whatever you append, so missing keys no longer crash
CSV exports or the printer — but returning every key is still good manners.

## Pip-installable plugins

In your own package's `pyproject.toml`:

```toml
[project.entry-points."hehelohe.modules"]
mysite = "my_package.modules:mysite"   # -> a @register-decorated coroutine
```

`pip install` it and hehelohe picks it up automatically.

## Tips

* `client` already has timeouts, redirects and the configured proxy applied —
  never create your own httpx client or import `requests`.
* Return `{"rateLimit": True}` on HTTP 429 / captcha pages; the retry
  engine (exponential backoff + optional proxy rotation) will take over.
* Tune behavior in `hehelohe.toml` instead of hardcoding numbers — see
  `hehelohe/defaults.toml` for every available knob.
* Verify discovery with `hehelohe --list-modules`.
