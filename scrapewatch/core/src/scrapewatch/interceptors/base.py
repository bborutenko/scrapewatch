"""Shared capture machinery: Event assembly, queue, background analyzer.

Source of truth: docs/components/interceptors.md §4 (Event assembly) and
§5 (the background analyzer), ADR-6 (fire-and-forget). This module owns
the two guarantees every interceptor relies on:

1. the capture path costs microseconds and never raises into user code;
2. analysis runs on one daemon thread behind a bounded queue — overflow
   drops the OLDEST events, never the newest, and counts them.

Interceptors contain zero business logic (interceptors.md §1): this
module builds Events and moves them; classification belongs to the core.
"""

import hashlib
import logging
import queue
import threading
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Callable

from ..core.engine import Engine
from ..core.event import BODY_SAMPLE_LIMIT, Event, JobRef
from ..core.verdict import Status, Verdict

__all__ = ["Analyzer", "build_event", "get_analyzer", "log_verdict"]

logger = logging.getLogger("scrapewatch.interceptors")

#: Responses over this cap contribute hash+length but no sample
#: (interceptors.md §4): the analyzer does not need megabytes to spot
#: a challenge page.
BODY_SIZE_CAP = 10 * 1024 * 1024

#: Bounded analyzer queue, overflow drops the oldest (ADR-6, §5).
DEFAULT_QUEUE_LIMIT = 10_000

#: Where processed verdicts go. Storage and alert channels arrive with
#: Phase 4 (storage-alerts.md); until then the sink is the log itself —
#: roadmap Phase 2's "verdicts start appearing in logs".
type VerdictSink = Callable[[Event, Verdict], None]


def log_verdict(event: Event, verdict: Verdict) -> None:
    """Default sink: non-ok verdicts surface as WARNING, ok stays at DEBUG."""
    if verdict.status is Status.OK:
        logger.debug("scrapewatch: ok %s", event.url)
    else:
        logger.warning(
            "scrapewatch: %s on %s — %s (detector=%s, confidence=%.2f)",
            verdict.status.value,
            event.url,
            verdict.reason,
            verdict.detector_id,
            verdict.confidence,
        )


def build_event(
    *,
    url: str,
    job: JobRef,
    method: str = "GET",
    status_code: int | None = None,
    headers: Mapping[str, str] | None = None,
    body: bytes | None = None,
    latency_ms: float | None = None,
    meta: dict[str, Any] | None = None,
) -> Event:
    """Assemble a contract-shaped Event from raw capture parts (§4).

    ``body`` is the raw body bytes, or ``None`` when the transport never
    produced one (connection failure, unread streaming response). Sample
    truncation, hashing, header lowercasing and content-type stripping
    happen here, so every interceptor yields identical Events.
    """
    lowered = {str(key).lower(): str(value) for key, value in (headers or {}).items()}

    content_type = lowered.get("content-type")
    if content_type is not None:
        content_type = content_type.split(";", 1)[0].strip() or None

    if body is None:
        sample, body_hash, body_length = "", None, None
    else:
        body_length = len(body)
        # size guard (§4): oversized bodies keep hash+length, drop the sample
        sample = "" if body_length > BODY_SIZE_CAP else body[:BODY_SAMPLE_LIMIT].decode("utf-8", errors="replace")
        body_hash = hashlib.sha256(body).hexdigest()

    return Event(
        url=url,
        job=job,
        captured_at=datetime.now(timezone.utc).isoformat(),
        method=method,
        status_code=status_code,
        headers=lowered,
        content_type=content_type,
        body_sample=sample,
        body_hash=body_hash,
        body_length=body_length,
        latency_ms=latency_ms,
        meta=meta or {},
    )


class Analyzer:
    """The background analyzer (interceptors.md §5): bounded queue + daemon thread.

    ``submit`` is the only method interceptor code calls: it never blocks
    (overflow drops the oldest event, counting ``dropped_events``) and
    never raises. Every worker iteration is wrapped in a catch-all:
    failures count ``analyzer_errors``, log at WARNING, and processing
    continues with the next event (ADR-6).

    ``engine=None`` resolves lazily to a packaged-rules Engine — built on
    the worker thread, so rule loading (disk I/O) never lands on the
    caller's request path. Per-session engines (custom ``rules=[...]``)
    are passed along with each event.
    """

    def __init__(
        self,
        engine: Engine | None = None,
        sink: VerdictSink | None = None,
        queue_limit: int = DEFAULT_QUEUE_LIMIT,
    ) -> None:
        self._engine = engine
        self._sink: VerdictSink = sink or log_verdict
        self._queue: queue.Queue[tuple[Event, Engine | None] | None] = queue.Queue(maxsize=queue_limit)
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

        #: Self-diagnostic counters (ADR-6); surfaced by `scrapewatch report` in Phase 4.
        self.dropped_events = 0
        self.analyzer_errors = 0
        self.processed_events = 0

    def submit(self, event: Event, engine: Engine | None = None) -> None:
        """Fire-and-forget enqueue; starts the worker thread on first call."""
        self._ensure_thread()
        while True:
            try:
                self._queue.put_nowait((event, engine))
                return
            except queue.Full:
                self._drop_oldest()

    def flush(self) -> None:
        """Block until every submitted event has been processed (tests/diagnostics)."""
        self._queue.join()

    def stop(self) -> None:
        """Drain and end the worker thread (test hook; daemon threads never block exit)."""
        self._ensure_thread()
        self._queue.put(None)  # stop sentinel
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _drop_oldest(self) -> None:
        """Overflow policy (ADR-6): oldest events are dropped, never the newest."""
        try:
            self._queue.get_nowait()
        except queue.Empty:
            return  # a concurrent consumer freed a slot; retry the put
        self.dropped_events += 1
        self._queue.task_done()  # keep flush()/join() accounting consistent

    def _ensure_thread(self) -> None:
        if self._thread is not None:
            return
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run, name="scrapewatch-analyzer", daemon=True
                )
                self._thread.start()

    def _run(self) -> None:
        if self._engine is None:
            self._engine = Engine()  # packaged rules, loaded off the caller's thread
        while True:
            item = self._queue.get()
            try:
                if item is None:  # stop sentinel
                    return
                event, engine = item
                verdict = (engine or self._engine).observe(event)  # type: ignore[union-attr]
                self._sink(event, verdict)
                self.processed_events += 1
            except Exception:  # §5: catch-all per iteration, then continue
                self.analyzer_errors += 1
                logger.warning("scrapewatch analyzer failed on an event", exc_info=True)
            finally:
                self._queue.task_done()


_default_analyzer: Analyzer | None = None
_default_lock = threading.Lock()


def get_analyzer() -> Analyzer:
    """The process-wide analyzer, started lazily on first watch()/job() (§5)."""
    global _default_analyzer
    if _default_analyzer is None:
        with _default_lock:
            if _default_analyzer is None:
                _default_analyzer = Analyzer()
    return _default_analyzer
