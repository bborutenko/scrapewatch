"""Analyzers: synchronous and asynchronous verdict processing.

SyncAnalyzer  — runs engine.observe() inline (for tests, reactive mode).
AsyncAnalyzer — queue + background thread (for passive watch()).
"""

import atexit
import hashlib
import queue
import threading
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from ..config import get_logger, get_settings
from .engine import Engine
from .event import Event, JobRef
from .verdict import Verdict

logger = get_logger()

__all__ = [
    "AnalyzerProtocol",
    "SyncAnalyzer",
    "AsyncAnalyzer",
    "build_event",
]


class AnalyzerProtocol(Protocol):
    """Common interface for analyzers."""

    def submit(self, event: Event, engine: Engine | None = None) -> None: ...
    def flush(self) -> None: ...
    def stop(self) -> None: ...


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
    """Build an Event from raw HTTP response data."""
    settings = get_settings()

    lowered = {str(key).lower(): str(value) for key, value in (headers or {}).items()}

    content_type = lowered.get("content-type")
    if content_type is not None:
        content_type = content_type.split(";", 1)[0].strip() or None

    if body is None:
        sample, body_hash, body_length = "", None, None
    else:
        body_length = len(body)
        sample = "" if body_length > settings.analyzer.body_size_cap else body[:settings.body_sample_limit].decode("utf-8", errors="replace")
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


class SyncAnalyzer:
    """Runs engine.observe() inline on the caller's thread."""

    def __init__(
        self,
        engine: Engine | None = None,
        sink: Callable[[Event, Verdict], None] | None = None,
    ) -> None:
        self._engine = engine
        self._sink = sink
        self.processed_events = 0
        self.analyzer_errors = 0

    def submit(self, event: Event, engine: Engine | None = None) -> None:
        """Process event synchronously."""
        try:
            actual_engine = engine or self._engine
            verdict = actual_engine.observe(event)
            if self._sink:
                self._sink(event, verdict)
            self.processed_events += 1
        except Exception as e:
            self.analyzer_errors += 1
            logger.error(f"SyncAnalyzer error processing event: {e!r}")

    def flush(self) -> None:
        """No-op for sync analyzer."""
        pass

    def stop(self) -> None:
        """No-op for sync analyzer."""
        pass


class AsyncAnalyzer:
    """Queue + background thread for async event processing."""

    def __init__(
        self,
        engine: Engine,
        sink: Callable[[Event, Verdict], None] | None = None,
        queue_limit: int | None = None,
        shutdown_timeout: float | None = None,
    ) -> None:
        settings = get_settings()
        self._engine = engine
        self._sink = sink
        self._queue: queue.Queue[tuple[Event, Engine] | None] = queue.Queue(
            maxsize=queue_limit if queue_limit is not None else settings.analyzer.queue_limit
        )
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._stopping = False
        self._shutdown_timeout = shutdown_timeout if shutdown_timeout is not None else settings.analyzer.shutdown_timeout
        self.analyzer_errors = 0
        self.processed_events = 0
        atexit.register(self._graceful_shutdown)


    def submit(self, event: Event, engine: Engine | None = None) -> None:
        """Add event to queue. Blocks if queue is full (backpressure)."""
        if self._stopping:
            return

        if engine is None:
            engine = self._engine

        self._ensure_thread()
        self._queue.put((event, engine))


    def flush(self) -> None:
        """Wait until all queued events are processed."""
        self._queue.join()


    def stop(self) -> None:
        """Stop the background thread and wait for queue to drain."""
        self._stopping = True
        self._ensure_thread()
        self._queue.put(None)
        
        if self._thread is not None:
            self._thread.join(timeout=self._shutdown_timeout)
            remaining = self._queue.qsize()
            if remaining > 0:
                logger.warning(
                    f"AsyncAnalyzer shutdown timeout: {remaining} events remain in queue"
                )
            self._thread = None


    def _graceful_shutdown(self) -> None:
        """Called by atexit on process termination."""
        if self._thread is not None:
            self.stop()


    def _ensure_thread(self) -> None:
        """Start the worker thread if not running."""
        if self._thread is not None:
            return
        
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="scrapewatch-analyzer", daemon=True)
                self._thread.start()


    def _run(self) -> None:
        """Worker thread main loop."""
        while True:
            item = self._queue.get()
            try:
                if item is None:
                    return
                
                event: Event = item[0]
                engine: Engine = item[1]

                verdict = engine.observe(event)

                if self._sink:
                    self._sink(event, verdict)

                self.processed_events += 1
            except Exception as e:
                self.analyzer_errors += 1
                logger.error(f"AsyncAnalyzer worker error: {e!r}")
            finally:
                self._queue.task_done()
