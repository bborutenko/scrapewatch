"""base.py: Event assembly (interceptors.md §4) and the analyzer's ADR-6 guarantees (§5)."""

import hashlib
import threading

from scrapewatch.core.engine import Engine
from scrapewatch.core.event import BODY_SAMPLE_LIMIT
from scrapewatch.core.event import JobRef
from scrapewatch.core.verdict import Status
from scrapewatch.interceptors import base
from scrapewatch.interceptors.base import Analyzer, build_event


def _jobref() -> JobRef:
    return JobRef(name="ebay-prices", run_id="run-1")


class _Collector:
    """Sink that records (url, status) pairs."""

    def __init__(self):
        self.pairs = []

    def __call__(self, event, verdict):
        self.pairs.append((event.url, verdict.status))


# --- build_event (§4) ---------------------------------------------------------


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
    body = b"prices" * 100
    event = build_event(url="https://x.example.com", job=_jobref(), body=body)

    assert event.body_hash == hashlib.sha256(body).hexdigest()
    assert event.body_length == len(body)


def test_sample_is_truncated_to_the_contract_limit():
    body = b"a" * (BODY_SAMPLE_LIMIT + 1024)
    event = build_event(url="https://x.example.com", job=_jobref(), body=body)

    assert len(event.body_sample) == BODY_SAMPLE_LIMIT
    assert event.body_length == len(body)


def test_oversized_bodies_keep_hash_and_length_but_no_sample(monkeypatch):
    monkeypatch.setattr(base, "BODY_SIZE_CAP", 10)
    event = build_event(url="https://x.example.com", job=_jobref(), body=b"x" * 11)

    assert event.body_sample == ""
    assert event.body_hash == hashlib.sha256(b"x" * 11).hexdigest()
    assert event.body_length == 11


def test_missing_body_stays_none_not_an_empty_hash():
    event = build_event(url="https://x.example.com", job=_jobref(), status_code=None)

    assert event.body_hash is None
    assert event.body_length is None
    assert event.body_sample == ""


def test_captured_at_is_iso_utc():
    event = build_event(url="https://x.example.com", job=_jobref())
    assert event.captured_at.endswith("+00:00")


# --- the analyzer (§5, ADR-6) --------------------------------------------------


def test_verdicts_are_computed_off_the_caller_thread():
    sink = _Collector()
    analyzer = Analyzer(engine=Engine(rules=[]), sink=sink)

    analyzer.submit(build_event(url="https://x.example.com", job=_jobref()))
    analyzer.flush()

    assert sink.pairs == [("https://x.example.com", Status.OK)]
    assert analyzer.processed_events == 1
    analyzer.stop()


def test_default_engine_is_the_packaged_ruleset():
    sink = _Collector()
    analyzer = Analyzer(sink=sink)
    challenge = build_event(
        url="https://x.example.com",
        job=_jobref(),
        status_code=200,
        body=b"<html><head><title>Just a moment...</title></head></html>",
    )

    analyzer.submit(challenge)
    analyzer.flush()

    assert sink.pairs == [("https://x.example.com", Status.BLOCKED)]
    analyzer.stop()


def test_overflow_drops_the_oldest_and_counts():
    gate = threading.Event()
    worker_busy = threading.Event()
    seen: list[str] = []

    def slow_sink(event, verdict):
        seen.append(event.url)
        worker_busy.set()
        gate.wait(timeout=5)

    analyzer = Analyzer(engine=Engine(rules=[]), sink=slow_sink, queue_limit=2)
    urls = [f"https://x.example.com/{i}" for i in range(4)]

    analyzer.submit(build_event(url=urls[0], job=_jobref()))
    assert worker_busy.wait(timeout=5)  # the worker holds event 0 inside the sink

    for url in urls[1:]:  # 1 and 2 fill the queue; 3 evicts the oldest (1)
        analyzer.submit(build_event(url=url, job=_jobref()))

    gate.set()
    analyzer.flush()

    assert analyzer.dropped_events == 1
    assert seen == [urls[0], urls[2], urls[3]]  # newest are never dropped
    analyzer.stop()


def test_sink_failure_counts_and_the_worker_survives():
    calls: list[str] = []

    def flaky_sink(event, verdict):
        calls.append(event.url)
        if len(calls) == 1:
            raise RuntimeError("sink exploded")

    analyzer = Analyzer(engine=Engine(rules=[]), sink=flaky_sink)
    analyzer.submit(build_event(url="https://a.example.com", job=_jobref()))
    analyzer.submit(build_event(url="https://b.example.com", job=_jobref()))
    analyzer.flush()

    assert analyzer.analyzer_errors == 1
    assert calls == ["https://a.example.com", "https://b.example.com"]
    analyzer.stop()


def test_broken_engine_is_contained(monkeypatch):
    # fault injection per §6: observe() is never-raise by contract, but even a
    # catastrophically broken engine must not kill the analyzer thread
    sink = _Collector()
    analyzer = Analyzer(engine=Engine(rules=[]), sink=sink)

    def explode(event):
        raise RuntimeError("boom")

    monkeypatch.setattr(analyzer._engine, "observe", explode)
    analyzer.submit(build_event(url="https://a.example.com", job=_jobref()))
    analyzer.flush()

    assert analyzer.analyzer_errors == 1
    assert sink.pairs == []
    analyzer.stop()


def test_stop_ends_the_worker_thread():
    analyzer = Analyzer(engine=Engine(rules=[]))
    analyzer.submit(build_event(url="https://a.example.com", job=_jobref()))
    analyzer.flush()

    analyzer.stop()

    assert analyzer._thread is None
