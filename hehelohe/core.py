"""hehelohe command line interface.

This module also doubles as the legacy import surface: the classic bundled
modules do ``from hehelohe.core import *`` and expect names like ``random``,
``string``, ``json``, ``re``, ``hashlib``, ``BeautifulSoup`` and ``httpx``
to be available. Do not remove those imports.
"""

# --------------------------------------------------------------------------
# Legacy star-import surface (used by bundled modules -- keep these!)
# --------------------------------------------------------------------------
from bs4 import BeautifulSoup
from termcolor import colored
import httpx
import trio

import os
import csv
from datetime import datetime
import time
import hashlib
import re
import sys
import string
import random
import json
# --------------------------------------------------------------------------

from argparse import ArgumentParser

from tqdm import tqdm

from hehelohe import __version__, __brand__
from hehelohe.config import load_config, cfg_get
from hehelohe.httpclient import ClientPool, ProxyPool, proxies_from_config
from hehelohe.output import print_result, export_csv
from hehelohe.registry import discover_modules, filter_modules
from hehelohe.runner import run_scan

DEBUG = False
EMAIL_FORMAT = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'


def _version_tuple(text):
    try:
        return tuple(int(part) for part in text.split(".") if part.isdigit())
    except Exception:
        return (0,)


def check_update(config):
    """Print a notice when a newer release exists on PyPI.

    Fully best-effort: any failure (offline, PyPI down, weird httpx build)
    is silently ignored, and hehelohe never installs or exits by itself.
    """
    try:
        response = httpx.get(
            config["core"]["update_url"],
            timeout=float(config["core"]["update_timeout"]),
        )
        latest = json.loads(response.text)["info"]["version"]
        if _version_tuple(latest) > _version_tuple(__version__):
            print(f"[!] hehelohe {latest} is available "
                  f"(you have {__version__}) -- pip install -U hehelohe")
    except Exception:
        return


def credit():
    """Print Credit"""
    print('Github : https://github.com/i-vt/hehelohe')
    print('hehelohe - check where an email is registered (a holehe reboot)')


def is_email(email, pattern=EMAIL_FORMAT):
    """Return True when the input string looks like an email address."""
    return bool(re.fullmatch(pattern, email))


def build_parser():
    parser = ArgumentParser(
        prog=__brand__,
        description=f"hehelohe v{__version__} -- check where an email is registered",
    )
    parser.add_argument("email", nargs='*', metavar='EMAIL',
                        help="Target email address(es)")
    parser.add_argument("--only-used", default=False, action="store_true",
                        dest="onlyused",
                        help="Displays only the sites used by the target email address.")
    parser.add_argument("--no-color", default=False, action="store_true",
                        dest="nocolor", help="Don't color terminal output")
    parser.add_argument("--no-clear", default=False, action="store_true",
                        dest="noclear",
                        help="Do not clear the terminal to display the results")
    parser.add_argument("-NP", "--no-password-recovery", default=False,
                        action="store_true", dest="nopasswordrecovery",
                        help="Do not try password recovery on the websites")
    parser.add_argument("-C", "--csv", default=False, action="store_true",
                        dest="csvoutput", help="Create a CSV with the results")
    parser.add_argument("-T", "--timeout", type=int, default=None,
                        dest="timeout", help="Set max timeout value")
    parser.add_argument("--concurrency", type=int, default=None,
                        dest="concurrency",
                        help="Max concurrent site checks")
    parser.add_argument("--retries", type=int, default=None, dest="retries",
                        help="Retries per site (backoff configured in the config file)")
    parser.add_argument("--no-second-pass", default=False, action="store_true",
                        dest="nosecondpass",
                        help="Disable the slow re-check of rate-limited sites")
    parser.add_argument("--proxy", action="append", default=[], dest="proxy",
                        metavar="URL",
                        help="Proxy URL (repeatable), e.g. "
                             "http://user:pass@host:port or socks5://host:port")
    parser.add_argument("--proxy-file", default=None, dest="proxyfile",
                        metavar="PATH",
                        help="Text file with one proxy URL per line")
    parser.add_argument("--proxy-rotation", choices=["round-robin", "random"],
                        default=None, dest="proxyrotation",
                        help="Proxy selection strategy")
    parser.add_argument("--config", default=None, dest="config",
                        metavar="PATH", help="Path to a hehelohe TOML config file")
    parser.add_argument("--plugins-dir", action="append", default=[],
                        dest="pluginsdir", metavar="DIR",
                        help="Extra directory with user modules (repeatable)")
    parser.add_argument("--include", default=None, dest="include",
                        metavar="NAMES",
                        help="Comma-separated modules to run (e.g. --include github,twitter)")
    parser.add_argument("--exclude", default=None, dest="exclude",
                        metavar="NAMES",
                        help="Comma-separated modules to skip")
    parser.add_argument("--list-modules", default=False, action="store_true",
                        dest="listmodules",
                        help="List all available modules and exit")
    parser.add_argument("--no-update-check", default=False, action="store_true",
                        dest="noupdatecheck", help="Skip the PyPI version check")
    parser.add_argument("--version", action="version",
                        version=f"{__brand__} {__version__}")
    return parser


def apply_cli_overrides(config, args):
    """CLI flags win over config file values."""
    if args.timeout is not None:
        config["core"]["timeout"] = args.timeout
    if args.concurrency is not None:
        config["core"]["concurrency"] = args.concurrency
    if args.retries is not None:
        config["retry"]["max_retries"] = args.retries
    if args.nosecondpass:
        config["retry"]["second_pass"] = False
    if args.noclear:
        config["core"]["clear_terminal"] = False

    if args.proxy:
        config["proxy"]["enabled"] = True
        config["proxy"]["proxies"] = list(args.proxy) + list(
            config["proxy"].get("proxies", []) or [])
    if args.proxyfile:
        config["proxy"]["enabled"] = True
        config["proxy"]["proxy_file"] = args.proxyfile
    if args.proxyrotation:
        config["proxy"]["rotation"] = args.proxyrotation
    return config


def build_client_pool(config):
    proxies, res_cfg = proxies_from_config(config)
    proxy_pool = ProxyPool(
        proxies,
        rotation=config["proxy"].get("rotation", "round-robin"),
        max_failures=config["proxy"].get("max_failures", 3),
        res_cfg=res_cfg,
    )
    return ClientPool(
        timeout=config["core"]["timeout"],
        concurrency=config["core"]["concurrency"],
        proxy_pool=proxy_pool,
    )


def list_modules(specs):
    print(f"{len(specs)} modules available:\n")
    width = max(len(name) for name in specs)
    by_category = {}
    for spec in specs.values():
        by_category.setdefault(spec.category, []).append(spec)
    for category in sorted(by_category):
        print(f"[{category}]")
        for spec in sorted(by_category[category], key=lambda s: s.name):
            flags = []
            if spec.method == "password recovery":
                flags.append("password-recovery")
            if spec.frequent_rate_limit:
                flags.append("frequent-rate-limit")
            if not spec.legacy:
                flags.append("new-style")
            suffix = f"  ({', '.join(flags)})" if flags else ""
            print(f"  {spec.name.ljust(width)}  {spec.domain}{suffix}")
        print()


async def scan_email(email, specs, config, args):
    client_pool = build_client_pool(config)
    start_time = time.time()
    progress = tqdm(total=len(specs), desc="checking sites", unit="site")
    try:
        data = await run_scan(list(specs.values()), email, client_pool,
                              config, progress)
    finally:
        progress.close()
        await client_pool.aclose()

    print_result(
        data, email, start_time, len(specs),
        no_color=args.nocolor,
        no_clear=args.noclear,
        only_used=args.onlyused,
        show_legend=cfg_get(config, "output.show_legend", True),
        clear_terminal=cfg_get(config, "core.clear_terminal", True),
    )
    credit()
    if args.csvoutput:
        name_file = export_csv(data, email,
                               prefix=cfg_get(config, "output.csv_prefix",
                                              "hehelohe"))
        print("All results have been exported to " + name_file)


async def maincore():
    args = build_parser().parse_args()
    config = apply_cli_overrides(load_config(args.config), args)

    if cfg_get(config, "core.check_update", True) and not args.noupdatecheck:
        check_update(config)
    credit()

    specs = discover_modules(config, extra_plugin_dirs=args.pluginsdir)
    specs = filter_modules(
        specs,
        include=args.include.split(",") if args.include else None,
        exclude=args.exclude.split(",") if args.exclude else None,
        no_password_recovery=args.nopasswordrecovery,
        password_recovery_names=cfg_get(config, "modules.password_recovery", []),
    )

    if args.listmodules:
        list_modules(specs)
        return

    if not args.email:
        sys.exit("[-] Please enter a target email ! \n"
                 "Example : hehelohe email@example.com")

    if not specs:
        sys.exit("[-] No modules selected (check --include/--exclude).")

    pattern = cfg_get(config, "core.email_regex", EMAIL_FORMAT)
    for email in args.email:
        if not is_email(email, pattern):
            print(f"[-] Skipping invalid email: {email}")
            continue
        await scan_email(email, specs, config, args)


def main():
    trio.run(maincore)


if __name__ == "__main__":
    main()
