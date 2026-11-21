"""httpx integration — imported only when an httpx client is wrapped.

This module is the only place allowed to ``import httpx`` at top level:
it is never imported unless the caller already holds an ``httpx.Client``
or ``httpx.AsyncClient``, which proves the library is installed (ADR-5).

Capture is fire-and-forget (ADR-6): building the Event takes microseconds,
analysis runs on the shared background analyzer, and no scrapewatch error
ever propagates into the request path. Zero business logic here — the
interceptor only assembles and hands over.
"""

import time
import uuid
from typing import Any

import httpx

from ..config import get_logger
from ..core.analyzer import AsyncAnalyzer, build_event
from ..core.engine import Engine
from ..core.event import JobRef

logger = get_logger()


class WatchedClient(httpx.Client):
    """Client subclass that routes every response through the capture hook."""

    #: Double-wrap marker (interceptors.md §3): watch(watch(x)) returns x unchanged.
    _scrapewatch_wrapped = True

    def __init__(
        self,
        *,
        job: str,
        analyzer: AsyncAnalyzer,
        engine: Engine,
        base_url: str = "",
        headers: dict | None = None,
        cookies: dict | None = None,
        auth: Any = None,
        timeout: Any = None,
        follow_redirects: bool = True,
        max_redirects: int = 20,
        trust_env: bool = True,
        proxy: Any = None,
        transport: Any = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            headers=headers or {},
            cookies=cookies or {},
            auth=auth,
            timeout=timeout,
            follow_redirects=follow_redirects,
            max_redirects=max_redirects,
            trust_env=trust_env,
            proxy=proxy,
            transport=transport,
        )
        self._scrapewatch_job = job
        self._scrapewatch_jobref = JobRef(name=job, run_id=uuid.uuid4().hex)
        self._scrapewatch_seen = 0
        self._scrapewatch_analyzer = analyzer
        self._scrapewatch_engine = engine

    def send(self, request: httpx.Request, *args: Any, **kwargs: Any) -> httpx.Response:
        started = time.perf_counter()
        try:
            response = super().send(request, *args, **kwargs)
        except Exception as exc:
            # Transport failure is blocked-adjacent signal (interceptors.md §7):
            # it still becomes an Event (status_code=None) — then the user's
            # exception is re-raised untouched.
            self._scrapewatch_capture_failure(exc, request, started)
            raise
        self._scrapewatch_observe(response, request, started)
        return response

    def _scrapewatch_observe(
        self, response: httpx.Response, request: httpx.Request, started: float
    ) -> None:
        """Build the Event and enqueue it; never raises into the request path."""
        try:
            self._scrapewatch_seen += 1
            body = self._scrapewatch_body(response)
            meta: dict[str, Any] = {"redirects": len(response.history)}
            if body is None:
                meta["body_skipped"] = "unread streaming response"
            # httpx.Response.elapsed is a timedelta
            latency_ms = (
                (response.elapsed.total_seconds() * 1000)
                if response.elapsed
                else (time.perf_counter() - started) * 1000
            )
            event = build_event(
                url=str(response.url),
                job=self._scrapewatch_jobref,
                method=str(request.method),
                status_code=response.status_code,
                headers=dict(response.headers),
                body=body,
                latency_ms=latency_ms,
                meta=meta,
            )
            self._scrapewatch_analyzer.submit(event, self._scrapewatch_engine)
        except Exception:
            logger.warning("response capture failed, request unaffected", exc_info=True)

    def _scrapewatch_capture_failure(
        self, exc: Exception, request: httpx.Request, started: float
    ) -> None:
        try:
            event = build_event(
                url=str(request.url),
                job=self._scrapewatch_jobref,
                method=str(request.method),
                status_code=None,
                latency_ms=(time.perf_counter() - started) * 1000,
                meta={"exception": repr(exc)},
            )
            self._scrapewatch_seen += 1
            self._scrapewatch_analyzer.submit(event, self._scrapewatch_engine)
        except Exception:
            logger.warning("failure capture failed, exception re-raised", exc_info=True)

    @staticmethod
    def _scrapewatch_body(response: httpx.Response) -> bytes | None:
        """Raw body bytes, or None when touching them would change behavior.

        In httpx, accessing .content reads the body if not already read.
        We always attempt to read it for capture purposes.
        """
        try:
            return response.content
        except Exception:
            return None


class WatchedAsyncClient(httpx.AsyncClient):
    """AsyncClient subclass that routes every response through the capture hook."""

    #: Double-wrap marker (interceptors.md §3): watch(watch(x)) returns x unchanged.
    _scrapewatch_wrapped = True

    def __init__(
        self,
        *,
        job: str,
        analyzer: AsyncAnalyzer,
        engine: Engine,
        base_url: str = "",
        headers: dict | None = None,
        cookies: dict | None = None,
        auth: Any = None,
        timeout: Any = None,
        follow_redirects: bool = True,
        max_redirects: int = 20,
        trust_env: bool = True,
        proxy: Any = None,
        transport: Any = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            headers=headers or {},
            cookies=cookies or {},
            auth=auth,
            timeout=timeout,
            follow_redirects=follow_redirects,
            max_redirects=max_redirects,
            trust_env=trust_env,
            proxy=proxy,
            transport=transport,
        )
        self._scrapewatch_job = job
        self._scrapewatch_jobref = JobRef(name=job, run_id=uuid.uuid4().hex)
        self._scrapewatch_seen = 0
        self._scrapewatch_analyzer = analyzer
        self._scrapewatch_engine = engine

    async def send(self, request: httpx.Request, *args: Any, **kwargs: Any) -> httpx.Response:
        started = time.perf_counter()
        try:
            response = await super().send(request, *args, **kwargs)
        except Exception as exc:
            self._scrapewatch_capture_failure(exc, request, started)
            raise
        self._scrapewatch_observe(response, request, started)
        return response

    def _scrapewatch_observe(
        self, response: httpx.Response, request: httpx.Request, started: float
    ) -> None:
        """Build the Event and enqueue it; never raises into the request path.

        Note: This is called from async context but enqueues synchronously.
        The queue and analyzer are thread-safe; async code enqueues without await.
        """
        try:
            self._scrapewatch_seen += 1
            body = self._scrapewatch_body(response)
            meta: dict[str, Any] = {"redirects": len(response.history)}
            if body is None:
                meta["body_skipped"] = "unread streaming response"
            latency_ms = (
                (response.elapsed.total_seconds() * 1000)
                if response.elapsed
                else (time.perf_counter() - started) * 1000
            )
            event = build_event(
                url=str(response.url),
                job=self._scrapewatch_jobref,
                method=str(request.method),
                status_code=response.status_code,
                headers=dict(response.headers),
                body=body,
                latency_ms=latency_ms,
                meta=meta,
            )
            self._scrapewatch_analyzer.submit(event, self._scrapewatch_engine)
        except Exception:
            logger.warning("response capture failed, request unaffected", exc_info=True)

    def _scrapewatch_capture_failure(
        self, exc: Exception, request: httpx.Request, started: float
    ) -> None:
        try:
            event = build_event(
                url=str(request.url),
                job=self._scrapewatch_jobref,
                method=str(request.method),
                status_code=None,
                latency_ms=(time.perf_counter() - started) * 1000,
                meta={"exception": repr(exc)},
            )
            self._scrapewatch_seen += 1
            self._scrapewatch_analyzer.submit(event, self._scrapewatch_engine)
        except Exception:
            logger.warning("failure capture failed, exception re-raised", exc_info=True)

    @staticmethod
    def _scrapewatch_body(response: httpx.Response) -> bytes | None:
        """Raw body bytes, or None when touching them would change behavior."""
        try:
            return response.content
        except Exception:
            return None


def wrap(
    client: httpx.Client | httpx.AsyncClient,
    *,
    job: str,
    analyzer: AsyncAnalyzer,
    engine: Engine,
) -> httpx.Client | httpx.AsyncClient:
    """Build a watched client carrying over the caller's client state.

    Args:
        client: The httpx.Client or httpx.AsyncClient to wrap
        job: Job name for this wrapped client
        analyzer: AsyncAnalyzer for background event processing
        engine: Engine for event classification

    Returns:
        WatchedClient or WatchedAsyncClient that observes all traffic
    """
    # Extract configuration from the original client
    base_url = getattr(client, "_base_url", None) or ""
    headers = dict(client.headers) if client.headers else None
    cookies = dict(client.cookies) if client.cookies else None
    auth = client.auth
    timeout = client.timeout
    follow_redirects = client.follow_redirects
    max_redirects = client.max_redirects
    trust_env = client.trust_env

    # Get proxy and transport if available
    proxy = getattr(client, "_proxy", None)
    transport = getattr(client, "_transport", None)

    # Create the watched instance with same configuration
    common_kwargs = {
        "job": job,
        "analyzer": analyzer,
        "engine": engine,
        "base_url": base_url,
        "headers": headers,
        "cookies": cookies,
        "auth": auth,
        "timeout": timeout,
        "follow_redirects": follow_redirects,
        "max_redirects": max_redirects,
        "trust_env": trust_env,
        "proxy": proxy,
        "transport": transport,
    }

    if isinstance(client, httpx.AsyncClient):
        watched = WatchedAsyncClient(**common_kwargs)
    else:
        watched = WatchedClient(**common_kwargs)

    return watched
