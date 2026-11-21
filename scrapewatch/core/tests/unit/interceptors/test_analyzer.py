"""Analyzer tests: SyncAnalyzer (inline) and AsyncAnalyzer (queue+thread)."""

import threading
import time

from scrapewatch.core.analyzer import (
    AsyncAnalyzer,
    SyncAnalyzer,
    build_event,
)
from scrapewatch.core.engine import Engine
from scrapewatch.core.event import JobRef
from scrapewatch.core.rules import load_rules
from scrapewatch.core.verdict import Status
from scrapewatch import get_settings


def _jobref() -> JobRef:
    return JobRef(name="ebay-prices", run_id="run-1")


class _Collector:
    def __init__(self):
        self.pairs = []

    def __call__(self, event, verdict):
        self.pairs.append((event.url, verdict.status))


def test_headers_are_lowercased_and_content_type_stripped():
    event = build_event(
        url="https://x.example.com",
        job=_jobref(),
        status_code=200,
        headers={"Content-Type": "text/html; charset=utf-8", "X-Mixed-Case": "1"},
        body=b"<html></html>",
    )

    assert event.headers == {"content-type": "text/html; charset=utf-8", "x-mixed-case": "1"}
    assert event.content_type == "text/html"


def test_body_hash_and_length_cover_the_full_body():
    import hashlib
    body = b"prices" * 100
    event = build_event(url="https://x.example.com", job=_jobref(), body=body)

    assert event.body_hash == hashlib.sha256(body).hexdigest()
    assert event.body_length == len(body)


def test_sample_is_truncated_to_the_contract_limit():
    settings = get_settings()
    body = b"a" * (settings.body_sample_limit + 1024)
    event = build_event(url="https://x.example.com", job=_jobref(), body=body)

    assert len(event.body_sample) == settings.body_sample_limit
    assert event.body_length == len(body)


def test_oversized_bodies_keep_hash_and_length_but_no_sample():
    import hashlib
    
    # Save current setting
    old_cap = get_settings().analyzer.body_size_cap
    
    # Configure small body_size_cap for test
    from scrapewatch import configure
    configure(body_size_cap=10)
    
    event = build_event(url="https://x.example.com", job=_jobref(), body=b"x" * 11)

    assert event.body_sample == ""
    assert event.body_hash == hashlib.sha256(b"x" * 11).hexdigest()
    assert event.body_length == 11
    
    # Restore original setting
    configure(body_size_cap=old_cap)


def test_missing_body_stays_none_not_an_empty_hash():
    event = build_event(url="https://x.example.com", job=_jobref(), status_code=None)

    assert event.body_hash is None
    assert event.body_length is None
    assert event.body_sample == ""


def test_captured_at_is_iso_utc():
    event = build_event(url="https://x.example.com", job=_jobref())
    assert event.captured_at.endswith("+00:00")


def test_sync_analyzer_runs_inline():
    sink = _Collector()
    analyzer = SyncAnalyzer(engine=Engine(rules=[]), sink=sink)

    analyzer.submit(build_event(url="https://x.example.com", job=_jobref()))

    assert sink.pairs == [("https://x.example.com", Status.OK)]
    assert analyzer.processed_events == 1


def test_sync_analyzer_error_is_caught(monkeypatch):
    sink = _Collector()
    analyzer = SyncAnalyzer(engine=Engine(rules=[]), sink=sink)

    def explode(event):
        raise RuntimeError("boom")

    monkeypatch.setattr(analyzer._engine, "observe", explode)
    analyzer.submit(build_event(url="https://x.example.com", job=_jobref()))

    assert analyzer.analyzer_errors == 1
    assert sink.pairs == []


def test_async_analyzer_verdicts_off_caller_thread():
    sink = _Collector()
    analyzer = AsyncAnalyzer(engine=Engine(rules=[]), sink=sink)

    analyzer.submit(build_event(url="https://x.example.com", job=_jobref()))
    analyzer.flush()

    assert sink.pairs == [("https://x.example.com", Status.OK)]
    assert analyzer.processed_events == 1
    analyzer.stop()


def test_async_analyzer_default_engine_is_empty_ruleset():
    sink = _Collector()
    analyzer = AsyncAnalyzer(engine=Engine(rules=load_rules()), sink=sink)
    challenge = build_event(
        url="https://x.example.com",
        job=_jobref(),
        status_code=200,
        body=b"<html><head><title>Just a moment...</title></head></html>",
    )

    analyzer.submit(challenge)
    analyzer.flush()

    assert sink.pairs == [("https://x.example.com", Status.OK)]
    analyzer.stop()


def test_async_analyzer_sink_failure_counts_and_worker_survives():
    calls: list[str] = []

    def flaky_sink(event, verdict):
        calls.append(event.url)
        if len(calls) == 1:
            raise RuntimeError("sink exploded")

    analyzer = AsyncAnalyzer(engine=Engine(rules=[]), sink=flaky_sink)
    analyzer.submit(build_event(url="https://a.example.com", job=_jobref()))
    analyzer.submit(build_event(url="https://b.example.com", job=_jobref()))
    analyzer.flush()

    assert analyzer.analyzer_errors == 1
    assert calls == ["https://a.example.com", "https://b.example.com"]
    analyzer.stop()


def test_async_analyzer_broken_engine_is_contained(monkeypatch):
    sink = _Collector()
    analyzer = AsyncAnalyzer(engine=Engine(rules=[]), sink=sink)

    def explode(event):
        raise RuntimeError("boom")

    monkeypatch.setattr(analyzer._engine, "observe", explode)
    analyzer.submit(build_event(url="https://a.example.com", job=_jobref()))
    analyzer.flush()

    assert analyzer.analyzer_errors == 1
    assert sink.pairs == []
    analyzer.stop()


def test_async_analyzer_stop_ends_worker_thread():
    analyzer = AsyncAnalyzer(engine=Engine(rules=[]))
    analyzer.submit(build_event(url="https://a.example.com", job=_jobref()))
    analyzer.flush()

    analyzer.stop()

    assert analyzer._thread is None


def test_async_analyzer_submit_blocks_when_queue_is_full():
    gate = threading.Event()
    worker_ready = threading.Event()

    def slow_sink(event, verdict):
        worker_ready.set()
        gate.wait(timeout=5)

    analyzer = AsyncAnalyzer(engine=Engine(rules=[]), sink=slow_sink, queue_limit=1)

    analyzer.submit(build_event(url="https://x.example.com/0", job=_jobref()))
    assert worker_ready.wait(timeout=2)

    submitted = threading.Event()

    def submit_blocked():
        analyzer.submit(build_event(url="https://x.example.com/1", job=_jobref()))
        submitted.set()

    t = threading.Thread(target=submit_blocked)
    t.start()

    blocked = not submitted.wait(timeout=0.2)

    gate.set()
    t.join(timeout=2)

    assert submitted.is_set()
    analyzer.flush()
    analyzer.stop()


def test_async_analyzer_processes_all_events_in_order():
    gate = threading.Event()
    processed: list[str] = []

    def ordered_sink(event, verdict):
        processed.append(event.url)
        gate.wait(timeout=5)

    analyzer = AsyncAnalyzer(engine=Engine(rules=[]), sink=ordered_sink, queue_limit=2)

    for i in range(3):
        gate.set()
        gate.clear()
        analyzer.submit(build_event(url=f"https://x.example.com/{i}", job=_jobref()))

    gate.set()
    analyzer.flush()

    assert processed == ["https://x.example.com/0", "https://x.example.com/1", "https://x.example.com/2"]
    assert analyzer.processed_events == 3
    analyzer.stop()


def test_submit_never_drops_events_under_load():
    processed: list[str] = []
    lock = threading.Lock()

    def sink(event, verdict):
        with lock:
            processed.append(event.url)

    analyzer = AsyncAnalyzer(engine=Engine(rules=[]), sink=sink, queue_limit=3)

    num_threads = 5
    events_per_thread = 10
    threads = []

    def submit_events(thread_id):
        for i in range(events_per_thread):
            analyzer.submit(build_event(url=f"https://x.example.com/{thread_id}/{i}", job=_jobref()))

    for i in range(num_threads):
        t = threading.Thread(target=submit_events, args=(i,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join(timeout=10)

    analyzer.flush()

    assert analyzer.processed_events == num_threads * events_per_thread
    assert len(processed) == num_threads * events_per_thread
    analyzer.stop()


def test_backpressure_processes_all_events_without_drop():
    processed: list[str] = []

    def sink(event, verdict):
        processed.append(event.url)

    analyzer = AsyncAnalyzer(engine=Engine(rules=[]), sink=sink, queue_limit=1)

    num_events = 20
    for i in range(num_events):
        analyzer.submit(build_event(url=f"https://x.example.com/{i}", job=_jobref()))

    analyzer.flush()

    assert len(processed) == num_events
    assert analyzer.processed_events == num_events
    analyzer.stop()