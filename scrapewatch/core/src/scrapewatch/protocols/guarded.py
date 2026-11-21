"""guarded() — Verdict-as-exception protocol.

Like watch(), but raises SwBlocked/SwGarbage exceptions on bad verdicts.
Designed for integration with retry libraries (tenacity, tenacity-style decorators).

TODO: Implement in Phase 2 (see docs/contracts/interfaces.md B.6)
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..client import WatchableClient


# TODO: Define SwBlocked, SwGarbage exceptions


def guarded(
    client: "WatchableClient",
    *,
    job: str,
    rules: Sequence[str] | None = None,
) -> "WatchableClient":
    """Wrap a client that raises on blocked/garbage verdicts.

    This is the exception-wrapper mode (ADR-8): wraps like watch(), but
    `blocked` verdicts raise `SwBlocked` and `garbage` verdicts raise
    `SwGarbage`. Designed for retry libraries — a fake-200 becomes a
    first-class retry trigger with one line.

    Args:
        client: A requests.Session, httpx.Client/AsyncClient, or Playwright Browser/BrowserContext
        job: Job name for this wrapped client
        rules: Optional list of custom rule file paths

    Returns:
        Wrapped client that raises on bad verdicts.

    Example:
        >>> import scrapewatch as sw
        >>> from tenacity import retry, retry_if_exception_type
        >>>
        >>> session = sw.guarded(requests.Session(), job="ebay-prices")
        >>>
        >>> @retry(retry=retry_if_exception_type(sw.SwBlocked))
        ... def get_listing(url):
        ...     return session.get(url)  # raises on challenge pages

    Note:
        Not yet implemented. See roadmap.md Phase 2.

    Raises:
        NotImplementedError: Always (not yet implemented)
    """
    raise NotImplementedError(
        "guarded() arrives with Phase 2 of the v0.1 roadmap; "
        "use watch() for passive observation in the meantime"
    )


__all__ = ["guarded"]
