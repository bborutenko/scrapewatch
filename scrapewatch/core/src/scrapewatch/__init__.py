"""Scrapewatch — observability for web scrapers."""

from .config import setup_logging
from .client import SUPPORTED_CLIENTS, WatchableClient, client_kind, watch

setup_logging()

__all__ = ["SUPPORTED_CLIENTS", "WatchableClient", "client_kind", "watch"]
