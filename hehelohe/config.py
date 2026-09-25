"""Configuration loading for hehelohe.

Every tunable value of the tool lives in ``defaults.toml`` (bundled with the
package). Users can override any of them, in increasing order of priority:

1. ``~/.config/hehelohe/hehelohe.toml``
2. ``./hehelohe.toml`` (current working directory)
3. a file passed with ``--config``
4. CLI flags (applied by the caller)
"""

import copy
import os
import sys

try:
    import tomllib  # Python >= 3.11
except ModuleNotFoundError:  # pragma: no cover - older Pythons
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        tomllib = None

_DEFAULTS_PATH = os.path.join(os.path.dirname(__file__), "defaults.toml")


def _user_config_path():
    return os.path.join(
        os.path.expanduser("~"), ".config", "hehelohe", "hehelohe.toml"
    )


def _local_config_path():
    return os.path.join(os.getcwd(), "hehelohe.toml")


def _read_toml(path):
    if tomllib is None:  # pragma: no cover
        sys.exit(
            "[-] Reading TOML config requires Python >= 3.11 or the 'tomli' "
            "package (pip install tomli)."
        )
    with open(path, "rb") as handle:
        return tomllib.load(handle)


def _deep_merge(base, override):
    """Recursively merge ``override`` into ``base`` (override wins)."""
    for key, value in override.items():
        if (
            key in base
            and isinstance(base[key], dict)
            and isinstance(value, dict)
        ):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def load_config(config_path=None):
    """Return the effective configuration as a nested dict.

    Keyword Arguments:
    config_path -- optional explicit config file (--config flag)
    """
    config = _read_toml(_DEFAULTS_PATH)
    config = copy.deepcopy(config)

    candidates = [_user_config_path(), _local_config_path()]
    if config_path:
        candidates.append(config_path)

    for path in candidates:
        if path and os.path.isfile(path):
            try:
                _deep_merge(config, _read_toml(path))
            except Exception as exc:
                sys.exit(f"[-] Could not parse config file {path}: {exc}")

    return config


def cfg_get(config, dotted, default=None):
    """Fetch ``section.subsection.key`` from the config dict."""
    node = config
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node
