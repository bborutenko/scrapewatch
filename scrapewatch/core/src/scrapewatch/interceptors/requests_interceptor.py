"""requests integration — imported only when a requests client is wrapped.

This module is the only place allowed to ``import requests`` at top level:
it is never imported unless the caller already holds a ``requests.Session``,
which proves the library is installed (ADR-5).

Capture is fire-and-forget (ADR-6): building the Event takes microseconds,
analysis runs on the shared background analyzer, and no scrapewatch error
ever propagates into the request path. Zero business logic here — the
interceptor only assembles and hands over.
"""

import time
import uuid
from collections.abc import Sequence
from typing import Any

import requests

from ..core.analyzer import AsyncAnalyzer, build_event
from ..core.engine import Engine
from ..core.event import JobRef
from ..core.rules import load_rules

_default_analyzer: AsyncAnalyzer | None = None


def _get_default_analyzer() -> AsyncAnalyzer:
    """Get or create the process-wide default analyzer."""
    global _default_analyzer
    if _default_analyzer is None:
        _default_analyzer = AsyncAnalyzer(engine=Engine(rules=load_rules()))
    return _default_analyzer


class WatchedSession(requests.Session):
    """Session subclass that routes every response through the capture hook."""

    #: Double-wrap marker (interceptors.md §3): watch(watch(x)) returns x unchanged.
    _scrapewatch_wrapped = True

    def __init__(self, *, job: str, engine: Engine | None = None) -> None:
        super().__init__()
        self._scrapewatch_job = job
        self._scrapewatch_jobref = JobRef(name=job, run_id=uuid.uuid4().hex)
        self._scrapewatch_seen = 0
        self._scrapewatch_analyzer = _get_default_analyzer()
        self._scrapewatch_engine = engine

    def request(self, *args: Any, **kwargs: Any) -> requests.Response:
        started = time.perf_counter()
        try:
            response = super().request(*args, **kwargs)
        except Exception as exc:
            # Transport failure is blocked-adjacent signal (interceptors.md §7):
            # it still becomes an Event (status_code=None) — then the user's
            # exception is re-raised untouched.
            self._scrapewatch_capture_failure(exc, args, kwargs, started)
            raise
        self._scrapewatch_observe(response, started)
        return response

    def _scrapewatch_observe(self, response: requests.Response, started: float) -> None:
        """Build the Event and enqueue it; never raises into the request path."""
        try:
            self._scrapewatch_seen += 1
            body = self._scrapewatch_body(response)
            meta: dict[str, Any] = {"redirects": len(response.history)}
            if body is None:
                meta["body_skipped"] = "unread streaming response"
            event = build_event(
                url=str(response.url),
                job=self._scrapewatch_jobref,
                method=str(getattr(response.request, "method", None) or "GET"),
                status_code=response.status_code,
                headers=dict(response.headers),
                body=body,
                latency_ms=(time.perf_counter() - started) * 1000,
                meta=meta,
            )
            self._scrapewatch_analyzer.submit(event, self._scrapewatch_engine)
        except Exception:
            # TODO: log when logging system is ready
            # logger.warning("scrapewatch: response capture failed; the request is unaffected", exc_info=True)
            pass

    def _scrapewatch_capture_failure(
        self, exc: Exception, args: tuple[Any, ...], kwargs: dict[str, Any], started: float
    ) -> None:
        try:
            url = str(kwargs.get("url", args[1] if len(args) > 1 else ""))
            method = str(kwargs.get("method", args[0] if args else "GET"))
            event = build_event(
                url=url,
                job=self._scrapewatch_jobref,
                method=method,
                status_code=None,
                latency_ms=(time.perf_counter() - started) * 1000,
                meta={"exception": repr(exc)},
            )
            self._scrapewatch_seen += 1
            self._scrapewatch_analyzer.submit(event, self._scrapewatch_engine)
        except Exception:
            # TODO: log when logging system is ready
            # logger.warning("scrapewatch: failure capture failed; the exception is re-raised untouched", exc_info=True)
            pass

    @staticmethod
    def _scrapewatch_body(response: requests.Response) -> bytes | None:
        """Raw body bytes, or None when touching them would change behavior.

        An unread ``stream=True`` response must not be drained by the
        observer — ADR-6 outranks detection. ``_content_consumed`` is
        requests' own flag, set once the body has been read; a normal
        (non-stream) request always arrives here consumed.
        """
        if not getattr(response, "_content_consumed", False):
            return None
        return response.content


def wrap(client: requests.Session, *, job: str, rules: Sequence[str] | None = None) -> WatchedSession:
    """Build a ``WatchedSession`` carrying over the caller's session state.

    ``rules`` layers user rule files over the packaged ones (B.1); an
    invalid rule file raises loudly right here — setup-time failure the
    user sees immediately (C.3.5), not something discovered mid-scrape.
    """
    engine = Engine(load_rules(rules)) if rules else None

    watched = WatchedSession(job=job, engine=engine)
    watched.headers.update(client.headers)
    watched.cookies.update(client.cookies)
    watched.auth = client.auth
    watched.proxies = client.proxies
    watched.params = client.params
    watched.verify = client.verify
    watched.cert = client.cert
    watched.trust_env = client.trust_env

    for prefix, adapter in client.adapters.items():
        watched.mount(prefix, adapter)

    return watched