"""guarded() — Verdict-as-exception protocol.

Like watch(), but raises SwBlocked/SwGarbage exceptions on bad verdicts.
Designed for integration with retry libraries (tenacity, tenacity-style decorators).
"""

import time
import uuid
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from ..config import get_logger
from ..core.analyzer import build_event
from ..core.event import JobRef
from ..core.exceptions import SwBlocked, SwGarbage
from ..core.verdict import Status, Verdict
from ..interceptors.client import (
    WatchableClient,
)

if TYPE_CHECKING:
    from ..core.engine import Engine

logger = get_logger()


class GuardedWrapper:
    """Wrapper that raises on bad verdicts.

    This wraps a watched client and checks verdicts after each request,
    raising SwBlocked or SwGarbage when appropriate.
    """

    _scrapewatch_wrapped = True

    def __init__(self, client: Any, job: str, engine: "Engine", analyzer: Any) -> None:
        self._client = client
        self._job = job
        self._engine = engine
        self._analyzer = analyzer
        self._job_ref = JobRef(name=job, run_id=uuid.uuid4().hex)

    def _check_verdict(self, response: Any, verdict: Verdict) -> None:
        """Check verdict and raise if blocked or garbage."""
        if verdict is None:
            return

        if verdict.status == Status.BLOCKED:
            raise SwBlocked(verdict, response)
        elif verdict.status == Status.GARBAGE:
            raise SwGarbage(verdict, response)

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._client, name)

        # Wrap methods that make requests
        if callable(attr) and name in ("get", "post", "put", "delete", "patch", "head", "options", "request"):
            return self._wrap_method(attr)

        return attr

    def _wrap_method(self, method: Any) -> Any:
        """Wrap a request method to check verdicts."""

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            try:
                response = method(*args, **kwargs)
            except Exception:
                # Transport errors are re-raised, not converted
                raise

            # Compute verdict synchronously
            verdict = self._compute_verdict(response, started)

            # Check and potentially raise
            self._check_verdict(response, verdict)

            return response

        return wrapped

    def _compute_verdict(self, response: Any, started: float) -> Verdict:
        """Compute verdict synchronously for a response."""
        try:
            # Extract response metadata
            url = str(getattr(response, "url", "unknown"))
            request = getattr(response, "request", None)
            method = str(getattr(request, "method", "GET") if request else "GET")
            status_code = getattr(response, "status_code", None)
            headers = dict(getattr(response, "headers", {}))

            # Body
            body = None
            if hasattr(response, "content"):
                try:
                    body = response.content
                except Exception:
                    pass

            latency_ms = (time.perf_counter() - started) * 1000

            event = build_event(
                url=url,
                job=self._job_ref,
                method=method,
                status_code=status_code,
                headers=headers,
                body=body,
                latency_ms=latency_ms,
                meta={},
            )

            return self._engine.observe(event)

        except Exception:
            return Verdict.unknown(reason="verdict computation failed", event_hash="")


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
        The wrapped client still observes and records events — reacting
        does not sacrifice history.
    """
    from .watch import watch

    if job == "":
        raise ValueError("job must be a non-empty string")

    # Double-wrap protection
    if getattr(client, "_scrapewatch_wrapped", False):
        logger.warning("guarded(): client already wrapped, returning unchanged")
        return client

    # First, wrap with watch() to get observation
    watched = watch(client, job=job, rules=rules)

    # Get engine from the watched client
    engine = watched._scrapewatch_engine
    analyzer = watched._scrapewatch_analyzer

    return GuardedWrapper(watched, job=job, engine=engine, analyzer=analyzer)


__all__ = ["guarded", "GuardedWrapper"]
