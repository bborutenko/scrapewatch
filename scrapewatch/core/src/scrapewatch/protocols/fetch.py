"""fetch() — Reactive request context protocol.

Execute a request and get the verdict synchronously, so the scraper can
react at the decision point (rotate proxy, retry, skip).

TODO: Implement in Phase 2 (see docs/contracts/interfaces.md B.5)
"""

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..core.verdict import Verdict


class FetchContext:
    """Context object for reactive fetch.

    TODO: Implement in Phase 2.
    """

    response: Any
    verdict: "Verdict"

    def retry(self) -> None:
        """Re-execute the request function."""
        raise NotImplementedError("FetchContext.retry() not yet implemented")

    def items(self, rows: list[dict]) -> None:
        """Attach extracted items for schema validation."""
        raise NotImplementedError("FetchContext.items() not yet implemented")


def fetch(
    fn: Callable,
    *args: Any,
    job: str,
    rules: Sequence[str] | None = None,
    **kwargs: Any,
) -> FetchContext:
    """Execute a request and get the verdict synchronously.

    This is the reactive mode (ADR-8): the verdict is computed synchronously
    and returned to the caller, so it can react at the decision point.

    Args:
        fn: The request function (e.g., session.get, client.get)
        *args: Arguments to pass to fn
        job: Job name for this fetch
        rules: Optional list of custom rule file paths
        **kwargs: Keyword arguments to pass to fn

    Returns:
        Context object with .response, .verdict, .retry(), .items()

    Example:
        >>> import scrapewatch as sw
        >>>
        >>> with sw.fetch(session.get, url, job="ebay-prices") as r:
        ...     if r.verdict.status == "blocked":
        ...         rotate_proxy()
        ...         r.retry()
        ...     elif r.verdict.status == "garbage":
        ...         skip(url)
        ...     else:
        ...         r.items(extract(r.response))

    Note:
        Not yet implemented. See roadmap.md Phase 2.

    Raises:
        NotImplementedError: Always (not yet implemented)
    """
    raise NotImplementedError(
        "fetch() arrives with Phase 2 of the v0.1 roadmap; "
        "use watch() for passive observation in the meantime"
    )


__all__ = ["fetch", "FetchContext"]
