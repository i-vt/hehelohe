"""Module registry: discovery, registration and normalization.

Three ways to add site checks (see docs/EXTENDING.md):

1. Built-in modules -- the classic holehe-style files under
   ``hehelohe/modules/<category>/<name>.py`` defining
   ``async def <name>(email, client, out)``.
2. Drop-in plugin directories -- ``~/.config/hehelohe/plugins``,
   ``./hehelohe_plugins`` or ``--plugins-dir``; both classic-style files and
   the new decorator style work there::

       from hehelohe import register

       @register(name="example", domain="example.com", category="social")
       async def example(email, client):
           r = await client.get(f"https://example.com/api?mail={email}")
           return {"exists": "taken" in r.text, "rateLimit": False}

   The decorator fills in every other result field for you.
3. Packaging entry points -- a pip package exposing functions under the
   ``hehelohe.modules`` entry-point group.

Plugin modules override built-ins with the same name, which makes patching
a broken site easy without forking the package.
"""

import importlib
import importlib.metadata
import importlib.util
import inspect
import os
import pkgutil
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

#: Keys every result dict is guaranteed to carry, with their defaults.
RESULT_TEMPLATE = {
    "name": "",
    "domain": "",
    "method": "register",
    "frequent_rate_limit": False,
    "rateLimit": False,
    "exists": False,
    "emailrecovery": None,
    "phoneNumber": None,
    "others": None,
    "error": False,
}

ENTRY_POINT_GROUP = "hehelohe.modules"


@dataclass
class ModuleSpec:
    """A single site check."""

    name: str
    domain: str
    func: Callable[[str, Any], Awaitable[dict]]
    category: str = "misc"
    method: str = "register"
    frequent_rate_limit: bool = False
    legacy: bool = False
    source: str = "builtin"


def normalize_result(raw, name, domain):
    """Fill every missing key of a module result with safe defaults.

    This is what makes CSV exports and the result printer crash-proof: no
    matter what a module returns (or forgets to return), downstream code
    always sees the same keys.
    """
    result = dict(RESULT_TEMPLATE)
    if isinstance(raw, dict):
        result.update(raw)
        # Keep the mandatory flags boolean no matter what the module sent.
        for key in ("rateLimit", "exists", "error", "frequent_rate_limit"):
            result[key] = bool(result.get(key, False))
    if not result["name"]:
        result["name"] = name
    if not result["domain"]:
        result["domain"] = domain
    return result


def error_result(name, domain, method="unknown", frequent_rate_limit=False,
                 message=None):
    """Standard result for a module that crashed or returned nothing."""
    result = normalize_result({}, name, domain)
    result.update({
        "method": method,
        "frequent_rate_limit": frequent_rate_limit,
        "rateLimit": False,
        "error": True,
    })
    if message:
        result["others"] = {"Message": message}
    return result


def register(name, domain, category="custom", method="register",
             frequent_rate_limit=False):
    """Decorator marking an async function as a hehelohe site module.

    The function receives ``(email, client)`` and returns a (possibly
    partial) result dict; all remaining fields are filled in automatically.
    """
    def decorator(func):
        func._hehelohe_meta = {
            "name": name,
            "domain": domain,
            "category": category,
            "method": method,
            "frequent_rate_limit": frequent_rate_limit,
        }
        return func
    return decorator


def _wrap_new_style(func, meta, source):
    async def run(email, client):
        raw = await func(email, client)
        if raw is None:
            raw = {}
        raw.setdefault("method", meta["method"])
        raw.setdefault("frequent_rate_limit", meta["frequent_rate_limit"])
        return normalize_result(raw, meta["name"], meta["domain"])

    return ModuleSpec(
        name=meta["name"],
        domain=meta["domain"],
        func=run,
        category=meta.get("category", "custom"),
        method=meta.get("method", "register"),
        frequent_rate_limit=bool(meta.get("frequent_rate_limit", False)),
        legacy=False,
        source=source,
    )


def _wrap_legacy(func, name, domain, category, source):
    """Adapt a classic ``async def name(email, client, out)`` module."""
    async def run(email, client):
        out = []
        try:
            await func(email, client, out)
        except Exception as exc:
            return error_result(name, domain, message=str(exc) or None)
        if not out:
            # The module appended nothing (silent drop): surface it as an
            # error result instead of losing the site entirely.
            return error_result(name, domain, message="module returned no result")
        raw = out[0]
        raw.setdefault("name", name)
        raw.setdefault("domain", domain)
        return normalize_result(raw, name, domain)

    return ModuleSpec(
        name=name,
        domain=domain,
        func=run,
        category=category,
        legacy=True,
        source=source,
    )


def _iter_decorated(module_obj):
    for _, member in inspect.getmembers(module_obj):
        meta = getattr(member, "_hehelohe_meta", None)
        if meta is not None and inspect.iscoroutinefunction(member):
            yield member, meta


def _walk_package(package_name):
    """Yield the dotted name of every module under a package, recursively."""
    package = importlib.import_module(package_name)
    for _, modname, is_pkg in pkgutil.iter_modules(package.__path__):
        full_name = f"{package_name}.{modname}"
        if is_pkg:
            yield from _walk_package(full_name)
        else:
            yield full_name


def discover_builtin(config):
    """Walk ``hehelohe.modules`` and adapt every classic module found."""
    domains = config.get("domains", {})
    specs = {}
    for full_name in _walk_package("hehelohe.modules"):
        module_obj = importlib.import_module(full_name)
        parts = full_name.split(".")
        site = parts[-1]
        category = parts[-2] if len(parts) > 2 else "misc"

        decorated = list(_iter_decorated(module_obj))
        if decorated:
            for func, meta in decorated:
                specs[meta["name"]] = _wrap_new_style(func, meta, "builtin")
            continue

        func = getattr(module_obj, site, None)
        if callable(func) and inspect.iscoroutinefunction(func):
            specs[site] = _wrap_legacy(
                func, site, domains.get(site, site), category, "builtin"
            )
    return specs


def _load_module_file(path):
    mod_name = "hehelohe_plugin_" + os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(mod_name, path)
    module_obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module_obj)
    return module_obj


def load_plugin_dir(directory, config, specs):
    """Load every .py file in a plugin directory into the specs dict."""
    domains = config.get("domains", {})
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(".py") or filename.startswith("_"):
            continue
        path = os.path.join(directory, filename)
        site = filename[:-3]
        try:
            module_obj = _load_module_file(path)
        except Exception as exc:
            print(f"[!] Could not load plugin {path}: {exc}")
            continue

        decorated = list(_iter_decorated(module_obj))
        if decorated:
            for func, meta in decorated:
                specs[meta["name"]] = _wrap_new_style(func, meta, f"plugin:{directory}")
        else:
            func = getattr(module_obj, site, None)
            if callable(func) and inspect.iscoroutinefunction(func):
                specs[site] = _wrap_legacy(
                    func, site, domains.get(site, site), "custom",
                    f"plugin:{directory}",
                )
            else:
                print(f"[!] Plugin {path} has no @register function and no "
                      f"async function named '{site}'; skipped.")


def load_entry_point_modules(specs):
    """Load pip-installed plugins from the ``hehelohe.modules`` group."""
    try:
        entry_points = importlib.metadata.entry_points()
        if hasattr(entry_points, "select"):
            group = entry_points.select(group=ENTRY_POINT_GROUP)
        else:  # pragma: no cover - old importlib.metadata API
            group = entry_points.get(ENTRY_POINT_GROUP, [])
    except Exception:
        return
    for entry_point in group:
        try:
            loaded = entry_point.load()
        except Exception as exc:
            print(f"[!] Could not load entry point {entry_point.name}: {exc}")
            continue
        meta = getattr(loaded, "_hehelohe_meta", None)
        if meta is not None and inspect.iscoroutinefunction(loaded):
            specs[meta["name"]] = _wrap_new_style(
                loaded, meta, f"entrypoint:{entry_point.name}")
        else:
            print(f"[!] Entry point {entry_point.name} is not a "
                  "@register-decorated coroutine; skipped.")


def default_plugin_dirs():
    return [
        os.path.join(os.path.expanduser("~"), ".config", "hehelohe", "plugins"),
        os.path.join(os.getcwd(), "hehelohe_plugins"),
    ]


def discover_modules(config, extra_plugin_dirs=None):
    """Collect every available module: built-ins, plugin dirs, entry points."""
    specs = discover_builtin(config)

    dirs = list(default_plugin_dirs())
    dirs.extend(config.get("modules", {}).get("plugin_dirs", []) or [])
    dirs.extend(extra_plugin_dirs or [])
    for directory in dirs:
        if directory and os.path.isdir(directory):
            load_plugin_dir(directory, config, specs)

    load_entry_point_modules(specs)
    return specs


def filter_modules(specs, include=None, exclude=None,
                   no_password_recovery=False, password_recovery_names=None):
    """Apply --include / --exclude / --no-password-recovery filtering."""
    selected = dict(specs)

    if no_password_recovery and password_recovery_names:
        selected = {
            name: spec for name, spec in selected.items()
            if name not in password_recovery_names
        }

    if include:
        wanted = {item.strip() for item in include}
        selected = {name: spec for name, spec in selected.items()
                    if name in wanted or spec.domain in wanted}

    if exclude:
        unwanted = {item.strip() for item in exclude}
        selected = {name: spec for name, spec in selected.items()
                    if name not in unwanted and spec.domain not in unwanted}

    return selected
