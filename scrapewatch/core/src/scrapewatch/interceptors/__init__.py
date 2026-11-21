"""Integration layer: one module per client library, imported lazily.

This package imports nothing third-party at top level; the wrap functions
import the interceptor submodule for the kind they need, and only that one —
an environment with just ``requests`` installed never touches the httpx
or playwright code paths (ADR-5).

Public API (watch, guarded, fetch) lives in scrapewatch.protocols/.
Client wrapping logic lives in client.py (types, detection, creation, dispatch).
"""

from .client import (
    ClientSpec,
    SUPPORTED_CLIENTS,
    WatchableClient,
    client_kind,
    create_async_analyzer,
    create_engine,
    create_sync_analyzer,
    get_supported_clients,
    wrap_client,
)

__all__ = [
    # Types
    "ClientSpec",
    "SUPPORTED_CLIENTS",
    "WatchableClient",
    # Detection
    "client_kind",
    # Creation
    "create_engine",
    "create_async_analyzer",
    "create_sync_analyzer",
    # Dispatch
    "wrap_client",
    "get_supported_clients",
]
