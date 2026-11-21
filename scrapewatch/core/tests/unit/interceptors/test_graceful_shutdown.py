"""Tests for AsyncAnalyzer graceful shutdown behavior."""

import multiprocessing
import os
import signal
import sys
import threading
import time

import pytest

from scrapewatch.core.analyzer import AsyncAnalyzer, build_event
from scrapewatch.core.engine import Engine
from scrapewatch.core.event import JobRef
from scrapewatch.core.rules import load_rules


def _worker_process_basic(events_count, queue_size, shutdown_timeout, result_queue):
    """Worker process that creates analyzer and processes events."""
    # Ensure correct Python path for spawned processes
    test_dir = os.path.dirname(os.path.abspath(__file__))
    core_root = os.path.dirname(os.path.dirname(os.path.dirname(test_dir)))
    sys.path.insert(0, core_root)
    
    def handle_sigterm(signum, frame):
        pass
    
    signal.signal(signal.SIGTERM, handle_sigterm)
    
    processed = []
    
    def sink(event, verdict):
        processed.append(event.url)
    
    engine = Engine(rules=load_rules())
    analyzer = AsyncAnalyzer(
        engine=engine,
        sink=sink,
        queue_limit=queue_size,
        shutdown_timeout=shutdown_timeout,
    )
    
    for i in range(events_count):
        event = build_event(
            url=f"https://example.com/page-{i}",
            job=JobRef(name="test", run_id="run-1"),
            status_code=200,
            body=b"<html><body>Test</body></html>",
        )
        analyzer.submit(event)
    
    time.sleep(0.2)
    
    os.kill(os.getpid(), signal.SIGTERM)
    
    time.sleep(shutdown_timeout + 1)
    
    result_queue.put({
        "processed": len(processed),
        "analyzer_processed": analyzer.processed_events,
        "errors": analyzer.analyzer_errors,
    })


def _worker_process_timeout(events_count, queue_size, shutdown_timeout, result_queue):
    """Worker process with slow sink to test timeout behavior."""
    # Ensure correct Python path for spawned processes
    test_dir = os.path.dirname(os.path.abspath(__file__))
    core_root = os.path.dirname(os.path.dirname(os.path.dirname(test_dir)))
    sys.path.insert(0, core_root)
    
    def handle_sigterm(signum, frame):
        pass
    
    signal.signal(signal.SIGTERM, handle_sigterm)
    
    processed = []
    
    def slow_sink(event, verdict):
        time.sleep(0.3)
        processed.append(event.url)
    
    engine = Engine(rules=load_rules())
    analyzer = AsyncAnalyzer(
        engine=engine,
        sink=slow_sink,
        queue_limit=queue_size,
        shutdown_timeout=shutdown_timeout,
    )
    
    for i in range(events_count):
        event = build_event(
            url=f"https://example.com/page-{i}",
            job=JobRef(name="test", run_id="run-1"),
        )
        analyzer.submit(event)
    
    time.sleep(0.1)
    
    os.kill(os.getpid(), signal.SIGTERM)
    
    time.sleep(shutdown_timeout + 1)
    
    result_queue.put({
        "processed": len(processed),
        "analyzer_processed": analyzer.processed_events,
        "remaining_in_queue": analyzer._queue.qsize(),
    })


def _worker_process_reject_during_shutdown(events_count, queue_size, shutdown_timeout, result_queue):
    """Worker process that tests reject during shutdown."""
    # Ensure correct Python path for spawned processes
    test_dir = os.path.dirname(os.path.abspath(__file__))
    core_root = os.path.dirname(os.path.dirname(os.path.dirname(test_dir)))
    sys.path.insert(0, core_root)
    
    def handle_sigterm(signum, frame):
        pass
    
    signal.signal(signal.SIGTERM, handle_sigterm)
    
    processed = []
    
    def sink(event, verdict):
        processed.append(event.url)
    
    engine = Engine(rules=load_rules())
    analyzer = AsyncAnalyzer(
        engine=engine,
        sink=sink,
        queue_limit=queue_size,
        shutdown_timeout=shutdown_timeout,
    )
    
    for i in range(events_count):
        event = build_event(
            url=f"https://example.com/page-{i}",
            job=JobRef(name="test", run_id="run-1"),
        )
        analyzer.submit(event)
    
    time.sleep(0.1)
    
    analyzer._stopping = True
    
    for i in range(5):
        event = build_event(
            url=f"https://example.com/rejected-{i}",
            job=JobRef(name="test", run_id="run-1"),
        )
        analyzer.submit(event)
    
    time.sleep(0.1)
    
    os.kill(os.getpid(), signal.SIGTERM)
    
    time.sleep(shutdown_timeout + 1)
    
    result_queue.put({
        "processed": len(processed),
        "analyzer_processed": analyzer.processed_events,
    })


def test_sigterm_triggers_graceful_shutdown():
    """SIGTERM should trigger graceful shutdown and process all events."""
    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue()
    
    p = ctx.Process(
        target=_worker_process_basic,
        args=(5, 100, 5.0, result_queue),
    )
    p.start()
    p.join(timeout=10)
    
    if p.is_alive():
        p.kill()
        p.join()
        pytest.fail("Process did not exit after SIGTERM")
    
    result = result_queue.get(timeout=1)
    assert result["processed"] == 5
    assert result["errors"] == 0
    assert p.exitcode == 0


def test_sigterm_processes_all_events_before_exit():
    """All events should be processed before process exits."""
    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue()
    
    p = ctx.Process(
        target=_worker_process_basic,
        args=(10, 100, 5.0, result_queue),
    )
    p.start()
    p.join(timeout=10)
    
    if p.is_alive():
        p.kill()
        p.join()
        pytest.fail("Process did not exit")
    
    result = result_queue.get(timeout=1)
    assert result["processed"] == 10
    assert result["analyzer_processed"] == 10


def test_sigterm_with_small_timeout_processes_partial():
    """Small timeout should process some events before forcing shutdown."""
    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue()
    
    p = ctx.Process(
        target=_worker_process_timeout,
        args=(10, 100, 0.5, result_queue),
    )
    p.start()
    p.join(timeout=10)
    
    result = result_queue.get(timeout=1)
    assert result["processed"] < 10
    assert result["processed"] > 0
    assert result["remaining_in_queue"] > 0


def test_sigterm_rejects_events_during_shutdown():
    """Events submitted during shutdown should be rejected."""
    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue()
    
    p = ctx.Process(
        target=_worker_process_reject_during_shutdown,
        args=(5, 100, 5.0, result_queue),
    )
    p.start()
    p.join(timeout=10)
    
    result = result_queue.get(timeout=1)
    assert result["processed"] == 5


def test_submit_during_shutdown_is_ignored():
    """Events submitted after shutdown started should be ignored."""
    processed = []

    def sink(event, verdict):
        processed.append(event.url)

    engine = Engine(rules=load_rules())
    analyzer = AsyncAnalyzer(engine=engine, sink=sink, queue_limit=100, shutdown_timeout=1.0)

    event1 = build_event(
        url="https://example.com/before-shutdown",
        job=JobRef(name="test", run_id="run-1"),
    )
    analyzer.submit(event1)

    analyzer._stopping = True

    event2 = build_event(
        url="https://example.com/after-shutdown",
        job=JobRef(name="test", run_id="run-1"),
    )
    analyzer.submit(event2)

    analyzer.flush()
    analyzer.stop()

    assert len(processed) == 1
    assert "before-shutdown" in processed[0]


def test_stop_waits_for_queue_to_drain():
    """stop() should wait for all events to be processed."""
    processed = []

    def slow_sink(event, verdict):
        time.sleep(0.1)
        processed.append(event.url)

    engine = Engine(rules=load_rules())
    analyzer = AsyncAnalyzer(engine=engine, sink=slow_sink, queue_limit=100, shutdown_timeout=5.0)

    for i in range(5):
        event = build_event(
            url=f"https://example.com/event-{i}",
            job=JobRef(name="test", run_id="run-1"),
        )
        analyzer.submit(event)

    analyzer.stop()

    assert len(processed) == 5


def test_stop_timeout_forces_shutdown():
    """stop() should force shutdown after timeout."""
    processed = []

    def very_slow_sink(event, verdict):
        time.sleep(0.5)
        processed.append(event.url)

    engine = Engine(rules=load_rules())
    analyzer = AsyncAnalyzer(engine=engine, sink=very_slow_sink, queue_limit=100, shutdown_timeout=0.5)

    for i in range(10):
        event = build_event(
            url=f"https://example.com/event-{i}",
            job=JobRef(name="test", run_id="run-1"),
        )
        analyzer.submit(event)

    time.sleep(0.1)
    analyzer.stop()

    assert len(processed) < 10
    assert analyzer._stopping is True


def test_graceful_shutdown_callback():
    """_graceful_shutdown should call stop() if thread is running."""
    engine = Engine(rules=load_rules())
    analyzer = AsyncAnalyzer(engine=engine, queue_limit=100, shutdown_timeout=1.0)

    event = build_event(
        url="https://example.com/test",
        job=JobRef(name="test", run_id="run-1"),
    )
    analyzer.submit(event)
    analyzer.flush()

    assert analyzer._thread is not None

    analyzer._graceful_shutdown()

    assert analyzer._stopping is True


def test_graceful_shutdown_does_nothing_if_not_started():
    """_graceful_shutdown should do nothing if thread never started."""
    engine = Engine(rules=load_rules())
    analyzer = AsyncAnalyzer(engine=engine, queue_limit=100, shutdown_timeout=1.0)

    assert analyzer._thread is None

    analyzer._graceful_shutdown()

    assert analyzer._stopping is False
