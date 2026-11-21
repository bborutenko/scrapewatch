"""Scrapewatch — observability for web scrapers."""

from .client import SUPPORTED_CLIENTS, WatchableClient, client_kind, watch
from .config import setup_logging, configure, get_settings

setup_logging()

__all__ = [
    "SUPPORTED_CLIENTS",
    "WatchableClient",
    "client_kind",
    "watch",
    "configure",
    "get_settings",
]
