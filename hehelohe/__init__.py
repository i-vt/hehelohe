"""hehelohe - check where an email address is registered.

Rebranded and heavily reworked fork of holehe: central configuration file,
residential proxy support, retries with exponential backoff and a plugin
system for writing new site modules.
"""

__version__ = "1.0.0"
__brand__ = "hehelohe"

from hehelohe.registry import register  # noqa: F401,E402  (public plugin API)
