"""Scrapewatch — observability for web scrapers."""

from .config import configure, get_settings, setup_logging
from .interceptors import SUPPORTED_CLIENTS, WatchableClient, client_kind
from .protocols import fetch, guarded, watch

setup_logging()

__all__ = [
    "SUPPORTED_CLIENTS",
    "WatchableClient",
    "client_kind",
    "watch",
    "guarded",
    "fetch",
    "configure",
    "get_settings",
]
