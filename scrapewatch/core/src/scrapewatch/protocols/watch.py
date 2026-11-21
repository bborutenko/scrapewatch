"""watch() — Passive observation protocol.

Wrap a client once, and all traffic through it gets observed. Verdicts
are delivered asynchronously to the background analyzer (ADR-6). The
user's scraping code runs unchanged.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from ..config import get_logger
from ..interceptors.client import (
    SUPPORTED_CLIENTS,
    WatchableClient,
    client_kind,
    create_async_analyzer,
    create_engine,
    wrap_client,
)

if TYPE_CHECKING:
    pass

logger = get_logger()


def watch(
    client: "WatchableClient",
    *,
    job: str,
    rules: Sequence[str] | None = None,
) -> "WatchableClient":
    """Wrap a scraper client so scrapewatch observes its traffic.

    This is the passive mode (ADR-6): verdicts are computed asynchronously
    on a background thread. The scraper's request path never blocks on
    scrapewatch, and no scrapewatch error ever propagates into user code.

    Args:
        client: A requests.Session, httpx.Client/AsyncClient, or Playwright Browser/BrowserContext
        job: Job name for this wrapped client (e.g., "ebay-prices")
        rules: Optional list of custom rule file paths

    Returns:
        Wrapped client that observes all traffic. Use it exactly like the original.

    Example:
        >>> import scrapewatch as sw
        >>> import requests
        >>>
        >>> session = sw.watch(requests.Session(), job="ebay-prices")
        >>> # All requests through session are now observed
        >>> response = session.get("https://example.com")

    Raises:
        ValueError: If job is empty
        TypeError: If client type is not supported
    """
    if job == "":
        raise ValueError("job must be a non-empty string")

    if getattr(client, "_scrapewatch_wrapped", False):
        logger.warning("watch(): client already wrapped, returning unchanged")
        return client

    kind = client_kind(client)

    if kind is None:
        supported = ", ".join(spec.kind for spec in SUPPORTED_CLIENTS)
        name = f"{type(client).__module__}.{type(client).__qualname__}"
        raise TypeError(f"watch() does not support {name}; supported clients: {supported}")

    engine = create_engine(rules)
    analyzer = create_async_analyzer(engine)

    return wrap_client(kind, client, job=job, analyzer=analyzer, engine=engine)
