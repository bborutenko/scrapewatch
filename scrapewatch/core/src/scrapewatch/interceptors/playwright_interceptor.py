"""Playwright integration — imported only when a Playwright Browser is wrapped.

This module is the only place allowed to ``import playwright`` at top level:
it is never imported unless the caller already holds a Playwright ``Browser``
or ``BrowserContext``, which proves the library is installed (ADR-5).

Capture is fire-and-forget (ADR-6): building the Event takes microseconds,
analysis runs on the shared background analyzer, and no scrapewatch error
ever propagates into the request path. Zero business logic here — the
interceptor only assembles and hands over.

Architecture (interceptors.md §2):
    Attach at BrowserContext level by default — cleaner multi-page semantics.
    Each context gets a response listener that captures every HTTP response.
"""

import time
import uuid
from typing import Any
from weakref import WeakSet

from ..config import get_logger
from ..core.analyzer import AsyncAnalyzer, build_event
from ..core.engine import Engine
from ..core.event import JobRef

logger = get_logger()

# Track timing for latency measurement: request -> start time
# Using thread-safe dict for both sync and async contexts
_request_timings: dict[str, float] = {}


class WatchedSyncBrowserContext:
    """Wrapper around Playwright sync BrowserContext that captures responses.

    Playwright doesn't subclass well (sync_api classes are proxies to Rust),
    so we use composition instead: wrap the context and intercept new pages.
    """

    #: Double-wrap marker (interceptors.md §3): watch(watch(x)) returns x unchanged.
    _scrapewatch_wrapped = True

    def __init__(
        self,
        context: Any,  # playwright.sync_api.BrowserContext
        job: str,
        analyzer: AsyncAnalyzer,
        engine: Engine,
    ) -> None:
        self._context = context
        self._scrapewatch_job = job
        self._scrapewatch_jobref = JobRef(name=job, run_id=uuid.uuid4().hex)
        self._scrapewatch_seen = 0
        self._scrapewatch_analyzer = analyzer
        self._scrapewatch_engine = engine
        self._pages: WeakSet = WeakSet()

        # Set up response listener on the context
        self._setup_response_listener()

    def _setup_response_listener(self) -> None:
        """Attach response listener to the context."""

        def on_response(response: Any) -> None:
            self._scrapewatch_observe(response)

        self._context.on("response", on_response)

        # Track request timings for latency
        def on_request(request: Any) -> None:
            _request_timings[request.url] = time.perf_counter()

        self._context.on("request", on_request)

        # Track failed requests (DNS errors, connection refused, etc.)
        def on_request_failed(request: Any) -> None:
            self._scrapewatch_capture_failure(request)

        self._context.on("requestfailed", on_request_failed)

    def _scrapewatch_observe(self, response: Any) -> None:
        """Build the Event and enqueue it; never raises."""
        try:
            self._scrapewatch_seen += 1

            # Calculate latency
            url = str(response.url)
            started = _request_timings.pop(url, None)
            if started is not None:
                latency_ms = (time.perf_counter() - started) * 1000
            else:
                timing = getattr(response, "timing", None)
                if timing:
                    latency_ms = timing.get("responseEnd", 0) - timing.get("requestStart", 0)
                else:
                    latency_ms = None

            request = response.request
            method = str(getattr(request, "method", "GET"))

            body = self._scrapewatch_body_sync(response)

            meta: dict[str, Any] = {"frame": str(response.frame.url) if response.frame else None}

            event = build_event(
                url=str(response.url),
                job=self._scrapewatch_jobref,
                method=method,
                status_code=response.status,
                headers=dict(response.headers),
                body=body,
                latency_ms=latency_ms,
                meta=meta,
            )
            self._scrapewatch_analyzer.submit(event, self._scrapewatch_engine)
        except Exception:
            logger.warning("response capture failed, request unaffected", exc_info=True)

    def _scrapewatch_capture_failure(self, request: Any) -> None:
        """Capture a failed request (no response received)."""
        try:
            url = str(request.url)
            started = _request_timings.pop(url, None)
            latency_ms = (time.perf_counter() - started) * 1000 if started else None

            failure = getattr(request, "failure", None)
            failure_text = failure() if failure else None

            meta: dict[str, Any] = {"exception": f"request_failed: {failure_text}"}

            event = build_event(
                url=str(request.url),
                job=self._scrapewatch_jobref,
                method=str(getattr(request, "method", "GET")),
                status_code=None,
                latency_ms=latency_ms,
                meta=meta,
            )
            self._scrapewatch_seen += 1
            self._scrapewatch_analyzer.submit(event, self._scrapewatch_engine)
        except Exception:
            logger.warning("failure capture failed", exc_info=True)

    @staticmethod
    def _scrapewatch_body_sync(response: Any) -> bytes | None:
        """Get body bytes synchronously, if available.

        Playwright's response.body() returns bytes in sync mode.
        """
        try:
            body = response.body()
            return body
        except Exception:
            return None

    # Proxy all other BrowserContext methods to the wrapped context
    def __getattr__(self, name: str) -> Any:
        return getattr(self._context, name)

    def new_page(self) -> Any:
        """Create a new page and track it."""
        page = self._context.new_page()
        self._pages.add(page)
        return page


class WatchedAsyncBrowserContext:
    """Wrapper around Playwright async BrowserContext that captures responses."""

    #: Double-wrap marker (interceptors.md §3): watch(watch(x)) returns x unchanged.
    _scrapewatch_wrapped = True

    def __init__(
        self,
        context: Any,  # playwright.async_api.BrowserContext
        job: str,
        analyzer: AsyncAnalyzer,
        engine: Engine,
    ) -> None:
        self._context = context
        self._scrapewatch_job = job
        self._scrapewatch_jobref = JobRef(name=job, run_id=uuid.uuid4().hex)
        self._scrapewatch_seen = 0
        self._scrapewatch_analyzer = analyzer
        self._scrapewatch_engine = engine
        self._pages: WeakSet = WeakSet()
        self._setup_response_listener()

    def _setup_response_listener(self) -> None:
        """Attach response listener to the context.

        Note: Event handlers in async Playwright run in the event loop,
        and our analyzer submit is sync/thread-safe, so this works.
        """

        def on_response(response: Any) -> None:
            self._scrapewatch_observe(response)

        self._context.on("response", on_response)

        def on_request(request: Any) -> None:
            _request_timings[request.url] = time.perf_counter()

        self._context.on("request", on_request)

        def on_request_failed(request: Any) -> None:
            self._scrapewatch_capture_failure(request)

        self._context.on("requestfailed", on_request_failed)

    def _scrapewatch_observe(self, response: Any) -> None:
        """Build the Event and enqueue it; never raises."""
        try:
            self._scrapewatch_seen += 1

            url = str(response.url)
            started = _request_timings.pop(url, None)
            latency_ms = (time.perf_counter() - started) * 1000 if started else None

            request = response.request
            method = str(getattr(request, "method", "GET"))

            # For async, we can't safely call response.body() from sync context
            # Skip body capture for async contexts unless already cached
            body = None
            if hasattr(response, "_body"):
                try:
                    body = response._body
                except Exception:
                    pass

            meta: dict[str, Any] = {"frame": str(response.frame.url) if response.frame else None}
            if body is None:
                meta["body_skipped"] = "async response body not cached"

            event = build_event(
                url=str(response.url),
                job=self._scrapewatch_jobref,
                method=method,
                status_code=response.status,
                headers=dict(response.headers),
                body=body,
                latency_ms=latency_ms,
                meta=meta,
            )
            self._scrapewatch_analyzer.submit(event, self._scrapewatch_engine)
        except Exception:
            logger.warning("response capture failed, request unaffected", exc_info=True)

    def _scrapewatch_capture_failure(self, request: Any) -> None:
        """Capture a failed request (no response received)."""
        try:
            url = str(request.url)
            started = _request_timings.pop(url, None)
            latency_ms = (time.perf_counter() - started) * 1000 if started else None

            failure = getattr(request, "failure", None)
            failure_text = failure() if failure else None

            meta: dict[str, Any] = {"exception": f"request_failed: {failure_text}"}

            event = build_event(
                url=str(request.url),
                job=self._scrapewatch_jobref,
                method=str(getattr(request, "method", "GET")),
                status_code=None,
                latency_ms=latency_ms,
                meta=meta,
            )
            self._scrapewatch_seen += 1
            self._scrapewatch_analyzer.submit(event, self._scrapewatch_engine)
        except Exception:
            logger.warning("failure capture failed", exc_info=True)

    # Proxy all other BrowserContext methods to the wrapped context
    def __getattr__(self, name: str) -> Any:
        return getattr(self._context, name)

    async def new_page(self) -> Any:
        """Create a new page and track it."""
        page = await self._context.new_page()
        self._pages.add(page)
        return page


class WatchedSyncBrowser:
    """Wrapper around Playwright sync Browser.

    Intercepts new_context() to return watched contexts.
    Browser-level wrap means all new contexts are automatically watched.
    """

    #: Double-wrap marker (interceptors.md §3): watch(watch(x)) returns x unchanged.
    _scrapewatch_wrapped = True

    def __init__(
        self,
        browser: Any,  # playwright.sync_api.Browser
        job: str,
        analyzer: AsyncAnalyzer,
        engine: Engine,
    ) -> None:
        self._browser = browser
        self._scrapewatch_job = job
        self._scrapewatch_analyzer = analyzer
        self._scrapewatch_engine = engine

    def new_context(self, **kwargs: Any) -> WatchedSyncBrowserContext:
        """Create a new watched browser context."""
        context = self._browser.new_context(**kwargs)
        return WatchedSyncBrowserContext(
            context,
            job=self._scrapewatch_job,
            analyzer=self._scrapewatch_analyzer,
            engine=self._scrapewatch_engine,
        )

    def new_page(self, **kwargs: Any) -> Any:
        """Create a new page in a new watched context.

        Convenience for simple scrapers that don't need multiple pages.
        """
        context = self.new_context(**kwargs)
        return context.new_page()

    # Proxy all other Browser methods
    def __getattr__(self, name: str) -> Any:
        return getattr(self._browser, name)

    def close(self) -> None:
        """Close the browser."""
        self._browser.close()

    def is_connected(self) -> bool:
        """Check if browser is connected."""
        return self._browser.is_connected()


class WatchedAsyncBrowser:
    """Wrapper around Playwright async Browser."""

    #: Double-wrap marker (interceptors.md §3): watch(watch(x)) returns x unchanged.
    _scrapewatch_wrapped = True

    def __init__(
        self,
        browser: Any,  # playwright.async_api.Browser
        job: str,
        analyzer: AsyncAnalyzer,
        engine: Engine,
    ) -> None:
        self._browser = browser
        self._scrapewatch_job = job
        self._scrapewatch_analyzer = analyzer
        self._scrapewatch_engine = engine

    async def new_context(self, **kwargs: Any) -> WatchedAsyncBrowserContext:
        """Create a new watched browser context."""
        context = await self._browser.new_context(**kwargs)
        return WatchedAsyncBrowserContext(
            context,
            job=self._scrapewatch_job,
            analyzer=self._scrapewatch_analyzer,
            engine=self._scrapewatch_engine,
        )

    async def new_page(self, **kwargs: Any) -> Any:
        """Create a new page in a new watched context."""
        context = await self.new_context(**kwargs)
        return await context.new_page()

    # Proxy all other Browser methods
    def __getattr__(self, name: str) -> Any:
        return getattr(self._browser, name)

    async def close(self) -> None:
        """Close the browser."""
        await self._browser.close()

    def is_connected(self) -> bool:
        """Check if browser is connected."""
        return self._browser.is_connected()


def wrap(
    client: Any,  # playwright.sync_api.Browser | playwright.async_api.Browser | BrowserContext
    *,
    job: str,
    analyzer: AsyncAnalyzer,
    engine: Engine,
) -> Any:
    """Wrap a Playwright Browser or BrowserContext.

    For Browser: returns a WatchedBrowser that intercepts new_context().
    For BrowserContext: returns a WatchedBrowserContext directly.

    Args:
        client: The Playwright Browser or BrowserContext to wrap
        job: Job name for this wrapped client
        analyzer: AsyncAnalyzer for background event processing
        engine: Engine for event classification

    Returns:
        Watched Browser or BrowserContext that observes all traffic
    """
    # Detect sync vs async and Browser vs BrowserContext
    class_name = type(client).__name__
    module_name = type(client).__module__

    is_async = "async_api" in module_name

    if "BrowserContext" in class_name:
        if is_async:
            return WatchedAsyncBrowserContext(client, job=job, analyzer=analyzer, engine=engine)
        else:
            return WatchedSyncBrowserContext(client, job=job, analyzer=analyzer, engine=engine)

    if "Browser" in class_name:
        if is_async:
            return WatchedAsyncBrowser(client, job=job, analyzer=analyzer, engine=engine)
        else:
            return WatchedSyncBrowser(client, job=job, analyzer=analyzer, engine=engine)

    raise TypeError(f"wrap() doesn't support {type(client).__module__}.{class_name}")
