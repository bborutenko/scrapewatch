"""Client wrapping logic — types, detection, and dispatch to interceptors.

This module is the single place that knows:
1. Which clients are supported (ClientSpec, SUPPORTED_CLIENTS)
2. How to detect client kind (client_kind)
3. How to create the capture pipeline (create_engine, create_analyzer)
4. How to dispatch to interceptors (wrap_client)

Third-party client libraries are optional extras, so nothing here imports
requests/httpx/playwright at import time (ADR-5). The public type exists
for type checkers only; runtime dispatch matches on the client's class
module and qualname.

The public API functions (watch, guarded, fetch) live in scrapewatch.protocols/.
"""

import importlib
import typing
from collections.abc import Sequence
from typing import Any

from ..core.analyzer import AsyncAnalyzer, SyncAnalyzer
from ..core.engine import Engine
from ..core.rules import load_rules


if typing.TYPE_CHECKING:
    import httpx
    import requests
    from playwright.async_api import Browser as AsyncBrowser
    from playwright.async_api import BrowserContext as AsyncBrowserContext
    from playwright.sync_api import Browser as SyncBrowser
    from playwright.sync_api import BrowserContext as SyncBrowserContext

    type WatchableClient = (
        requests.Session
        | httpx.Client
        | httpx.AsyncClient
        | SyncBrowser
        | SyncBrowserContext
        | AsyncBrowser
        | AsyncBrowserContext
    )
else:
    # At runtime, WatchableClient is just an alias for Any
    WatchableClient = typing.Any


class ClientSpec(typing.NamedTuple):
    """One supported client library: its import name and recognizable classes.

    ``kind`` triples as the extras name and the top-level module:
    ``kind == "requests"`` means ``pip install scrapewatch[requests]`` and
    classes defined under ``requests.*``.
    """

    kind: str
    qualnames: frozenset[str]

    def matches(self, client: object) -> bool:
        return any(
            base.__module__.split(".")[0] == self.kind and base.__qualname__ in self.qualnames
            for base in type(client).__mro__
        )


#: The catalog of clients ``watch()`` can wrap. Public on purpose: this is
#: the library's feature list.
SUPPORTED_CLIENTS: tuple[ClientSpec, ...] = (
    ClientSpec("requests", frozenset({"Session"})),
    ClientSpec("httpx", frozenset({"Client", "AsyncClient"})),
    ClientSpec("playwright", frozenset({"Browser", "BrowserContext"})),
)


def client_kind(client: object) -> str | None:
    """Library kind of ``client`` (``"requests"``, ``"httpx"``, ``"playwright"``).

    Returns ``None`` for anything else. The MRO walk inside
    ``ClientSpec.matches`` keeps subclasses of a supported client
    recognizable, so wrapped/rebuilt clients stay watchable.
    """
    return next((spec.kind for spec in SUPPORTED_CLIENTS if spec.matches(client)), None)



# kind -> interceptor submodule of this package
_IMPLEMENTED: dict[str, str] = {
    "requests": "requests_interceptor",
    "httpx": "httpx_interceptor",
    "playwright": "playwright_interceptor",
}



def create_engine(rules: Sequence[str] | None = None) -> Engine:
    """Create an Engine with packaged rules and optional custom rules.

    Args:
        rules: Optional list of custom rule file paths

    Returns:
        Engine instance ready for event classification
    """
    return Engine(rules=load_rules(rules or ()))


def create_async_analyzer(engine: Engine) -> AsyncAnalyzer:
    """Create an AsyncAnalyzer for passive watch mode.

    Args:
        engine: Engine for event classification

    Returns:
        AsyncAnalyzer with background thread for async processing
    """
    return AsyncAnalyzer(engine=engine)


def create_sync_analyzer(engine: Engine) -> SyncAnalyzer:
    """Create a SyncAnalyzer for reactive modes (fetch, guarded).

    Args:
        engine: Engine for event classification

    Returns:
        SyncAnalyzer that processes events inline
    """
    return SyncAnalyzer(engine=engine)


def wrap_client(
    kind: str,
    client: Any,
    *,
    job: str,
    analyzer: AsyncAnalyzer,
    engine: Engine,
) -> Any:
    """Wrap client with the interceptor registered for its library kind.

    Args:
        kind: Client library kind ("requests", "httpx", "playwright")
        client: The client instance to wrap
        job: Job name for this wrapped client
        analyzer: AsyncAnalyzer for background event processing
        engine: Engine for event classification

    Returns:
        Wrapped client that observes all traffic

    Raises:
        TypeError: If client kind is not supported
    """
    module_name = _IMPLEMENTED.get(kind)

    if module_name is None:
        supported = ", ".join(_IMPLEMENTED.keys())
        raise TypeError(f"unknown client kind {kind!r}; supported: {supported}")

    module = importlib.import_module(f".{module_name}", __package__)
    return module.wrap(client, job=job, analyzer=analyzer, engine=engine)


def get_supported_clients() -> tuple[str, ...]:
    """Return tuple of supported client library kinds."""
    return tuple(_IMPLEMENTED.keys())


__all__ = [
    "WatchableClient",
    "ClientSpec",
    "SUPPORTED_CLIENTS",

    "client_kind",

    "create_engine",
    "create_async_analyzer",
    "create_sync_analyzer",

    "wrap_client",
    "get_supported_clients",
]
