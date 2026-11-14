"""Integration layer: one module per client library, imported lazily.

This package imports nothing third-party at top level; ``wrap_client``
imports the interceptor submodule for the kind it is asked about, and only
that one — an environment with just ``requests`` installed never touches
the httpx or playwright code paths (ADR-5).
"""

import importlib
from typing import Any

# kind -> interceptor submodule of this package
_IMPLEMENTED: dict[str, str] = {
    "requests": "requests_interceptor",
}

# recognized by client_kind(), but the interceptor itself arrives with the
# v0.1 interceptors milestone (docs/components/interceptors.md)
_PLANNED = ("httpx", "playwright")


def wrap_client(kind: str, client: Any, *, job: str) -> Any:
    """Wrap ``client`` with the interceptor registered for its library kind."""

    if kind in _PLANNED:
        raise NotImplementedError(
            f"the {kind} interceptor arrives with the v0.1 interceptors milestone; "
            "requests is wired today"
        )
    
    module_name = _IMPLEMENTED.get(kind)

    if module_name is None:
        raise TypeError(f"unknown client kind {kind!r}")
    
    module = importlib.import_module(f".{module_name}", __package__)
    return module.wrap(client, job=job)
