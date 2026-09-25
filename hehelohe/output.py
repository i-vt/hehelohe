"""Terminal output and CSV export."""

import csv
import time
from datetime import datetime

from termcolor import colored


def _paint(text, color, no_color):
    return text if no_color else colored(text, color)


def print_result(data, email, start_time, total, no_color=False,
                 no_clear=False, only_used=False, show_legend=True,
                 clear_terminal=True):
    """Pretty-print scan results.

    Screen clearing uses \\033[2J (visible screen only) instead of the old
    \\033[J, which wiped the terminal scrollback history on macOS/Linux and
    destroyed previous results.
    """
    description = (
        _paint("[+] Email used", "green", no_color) + ","
        + _paint(" [-] Email not used", "magenta", no_color) + ","
        + _paint(" [x] Rate limit", "yellow", no_color) + ","
        + _paint(" [!] Error", "red", no_color)
    )
    if clear_terminal and not no_clear:
        print("\033[H\033[2J")
    else:
        print("\n")
    print("*" * (len(email) + 6))
    print("   " + email)
    print("*" * (len(email) + 6))

    for result in data:
        others = result.get("others") or {}
        if result.get("rateLimit") and not only_used:
            print(_paint("[x] " + result["domain"], "yellow", no_color))
        elif result.get("error") and not only_used:
            toprint = ""
            if isinstance(others, dict):
                message = others.get("Message") or others.get("errorMessage")
                if message:
                    toprint = " Error message: " + str(message)
            print(_paint("[!] " + result["domain"] + toprint, "red", no_color))
        elif not result.get("exists") and not only_used:
            print(_paint("[-] " + result["domain"], "magenta", no_color))
        elif result.get("exists"):
            toprint = ""
            if result.get("emailrecovery"):
                toprint += " " + str(result["emailrecovery"])
            if result.get("phoneNumber"):
                toprint += " / " + str(result["phoneNumber"])
            if isinstance(others, dict):
                if "FullName" in others:
                    toprint += " / FullName " + str(others["FullName"])
                if "Date, time of the creation" in others:
                    toprint += (" / Date, time of the creation "
                                + str(others["Date, time of the creation"]))
            print(_paint("[+] " + result["domain"] + toprint, "green", no_color))

    if show_legend:
        print("\n" + description)
    print(f"{total} websites checked in "
          f"{round(time.time() - start_time, 2)} seconds")


def export_csv(data, email, prefix="hehelohe"):
    """Write results to ``<prefix>_<timestamp>_<email>_results.csv``.

    Field names are the union of every key present in the data: modules do
    not all return the exact same dict shape, and using ``data[0].keys()``
    crashed the export whenever the first row happened to be an error row.
    """
    now = datetime.now()
    timestamp = datetime.timestamp(now)
    name_file = f"{prefix}_{round(timestamp)}_{email}_results.csv"
    all_keys = list(dict.fromkeys(key for row in data for key in row.keys()))
    with open(name_file, "w", encoding="utf8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=all_keys,
                                restval="", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(data)
    return name_file
