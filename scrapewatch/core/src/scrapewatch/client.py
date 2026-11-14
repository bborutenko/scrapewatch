"""The single place that knows which scraper clients ``watch()`` can wrap.

Third-party client libraries are optional extras, so nothing here imports
requests/httpx/playwright at import time (ADR-5). The public type exists
for type checkers only; runtime dispatch matches on the client's class
module and qualname, which needs no imports at all.
"""

import typing

from .interceptors import wrap_client

if typing.TYPE_CHECKING:
    import httpx
    import requests
    from playwright.async_api import Browser as AsyncBrowser
    from playwright.async_api import BrowserContext as AsyncBrowserContext
    from playwright.sync_api import Browser as SyncBrowser
    from playwright.sync_api import BrowserContext as SyncBrowserContext

__all__ = [
    "ClientSpec",
    "SUPPORTED_CLIENTS",
    "WatchableClient",
    "client_kind",
    "watch",
]


type WatchableClient = (
    requests.Session
    | httpx.Client
    | httpx.AsyncClient
    | SyncBrowser
    | SyncBrowserContext
    | AsyncBrowser
    | AsyncBrowserContext
)


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


def watch[C: WatchableClient](client: C, *, job: str) -> C:
    """Wrap a scraper client so scrapewatch observes its traffic.

    The client's library must be installed for the object to exist at all,
    so availability is not re-checked here: the interceptor module for the
    detected kind is imported lazily, and only that one (ADR-5).
    """
    if job == "":
        raise ValueError("job must be a non-empty string")

    kind = client_kind(client)

    if kind is None:
        supported = ", ".join(spec.kind for spec in SUPPORTED_CLIENTS)
        name = f"{type(client).__module__}.{type(client).__qualname__}"
        raise TypeError(f"watch() does not support {name}; supported clients: {supported}")

    return wrap_client(kind, client, job=job)
