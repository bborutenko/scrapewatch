"""fetch() — Reactive request context protocol.

Execute a request and get the verdict synchronously, so the scraper can
react at the decision point (rotate proxy, retry, skip).
"""

import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from ..core.analyzer import build_event
from ..core.engine import Engine
from ..core.event import JobRef
from ..core.verdict import Verdict
from ..interceptors.client import create_engine

if TYPE_CHECKING:
    from collections.abc import Sequence


class FetchContext:
    """Context object for reactive fetch.

    Provides synchronous access to verdict and response, with retry capability.
    """

    __slots__ = ("_fn", "_args", "_kwargs", "_engine", "_job_ref", "response", "verdict")

    def __init__(
        self,
        fn: Callable,
        args: tuple,
        kwargs: dict,
        engine: Engine,
        job_ref: JobRef,
    ) -> None:
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self._engine = engine
        self._job_ref = job_ref
        self.response: Any = None
        self.verdict: Verdict | None = None

    def retry(self) -> None:
        """Re-execute the request function.

        The response and verdict are updated in-place.
        """
        started = time.perf_counter()
        try:
            self.response = self._fn(*self._args, **self._kwargs)
            self._observe(self.response, started)
        except Exception as exc:
            self._capture_failure(exc, started)
            raise

    def items(self, rows: list[dict]) -> None:
        """Attach extracted items for schema validation.

        Note: Schema validation is Phase 3 — this is a stub.
        """
        # TODO: In Phase 3, validate rows against schema and update drift metrics
        pass

    def _observe(self, response: Any, started: float) -> None:
        """Build Event and compute verdict synchronously."""
        try:
            # Extract response metadata
            url = str(getattr(response, "url", "unknown"))
            request = getattr(response, "request", None)
            method = str(getattr(request, "method", "GET") if request else "GET")
            status_code = getattr(response, "status_code", None)

            # Headers
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

            # Compute verdict synchronously
            self.verdict = self._engine.observe(event)

        except Exception:
            # If observation fails, create unknown verdict
            self.verdict = Verdict.unknown(reason="observation failed", event_hash="")

    def _capture_failure(self, exc: Exception, started: float) -> None:
        """Build Event for failed request."""
        url = "unknown"
        method = "GET"

        # Try to extract URL from kwargs or args
        if "url" in self._kwargs:
            url = str(self._kwargs["url"])
        elif len(self._args) > 0:
            url = str(self._args[0])

        latency_ms = (time.perf_counter() - started) * 1000

        event = build_event(
            url=url,
            job=self._job_ref,
            method=method,
            status_code=None,
            latency_ms=latency_ms,
            meta={"exception": repr(exc)},
        )

        self.verdict = self._engine.observe(event)


@contextmanager
def fetch(
    fn: Callable,
    *args: Any,
    job: str,
    rules: "Sequence[str] | None" = None,
    **kwargs: Any,
):
    """Execute a request and get the verdict synchronously.

    This is the reactive mode (ADR-8): the verdict is computed synchronously
    and returned to the caller, so it can react at the decision point.

    Args:
        fn: The request function (e.g., session.get, client.get)
        *args: Arguments to pass to fn
        job: Job name for this fetch
        rules: Optional list of custom rule file paths
        **kwargs: Keyword arguments to pass to fn

    Yields:
        FetchContext with .response, .verdict, .retry(), .items()

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
    """
    if job == "":
        raise ValueError("job must be a non-empty string")

    # Create engine for reactive mode
    engine = create_engine(rules)

    # Create job ref for this fetch
    job_ref = JobRef(name=job, run_id=uuid.uuid4().hex)

    # Create context
    ctx = FetchContext(fn, args, kwargs, engine, job_ref)

    # Execute first request
    try:
        ctx.retry()  # This sets response and verdict
    except Exception:
        # Even on failure, we have a verdict
        raise

    try:
        yield ctx
    finally:
        # Context cleanup - events were processed inline
        pass


__all__ = ["fetch", "FetchContext"]
