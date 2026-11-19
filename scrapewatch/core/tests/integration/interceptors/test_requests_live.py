"""WatchedSession against a real local HTTP server: sockets, redirects, cookies, verdicts."""

import logging

import pytest
import requests

from scrapewatch.interceptors.base import get_analyzer
from scrapewatch.interceptors.requests_interceptor import wrap


def test_real_request_is_observed(local_server):
    watched = wrap(requests.Session(), job="ebay-prices")

    response = watched.get(local_server)

    assert response.status_code == 200
    assert watched._scrapewatch_seen == 1


def test_redirects_yield_the_final_response_once(local_server):
    watched = wrap(requests.Session(), job="ebay-prices")

    response = watched.get(f"{local_server}/redirect")

    assert response.status_code == 200
    assert response.url.endswith("/final")
    assert len(response.history) == 1
    assert watched._scrapewatch_seen == 1


def test_session_cookies_persist_across_real_requests(local_server):
    watched = wrap(requests.Session(), job="ebay-prices")
    watched.get(local_server)
    watched.get(local_server)

    assert watched._scrapewatch_seen == 2


# --- verdicts flow through the analyzer (roadmap Phase 2: "verdicts in logs") ---


def test_capture_does_not_touch_the_user_visible_response(local_server):
    watched = wrap(requests.Session(), job="ebay-prices")

    response = watched.get(local_server)

    assert response.text == "<html>prices</html>"
    assert response.headers["Content-Type"] == "text/html"


def test_fake_200_challenge_verdict_appears_in_logs(local_server, caplog):
    analyzer = get_analyzer()
    watched = wrap(requests.Session(), job="ebay-prices")

    with caplog.at_level(logging.WARNING, logger="scrapewatch"):
        response = watched.get(f"{local_server}/challenge")
        analyzer.flush()

    assert response.status_code == 200  # the user sees a "successful" response
    assert "blocked" in caplog.text
    assert "cloudflare-challenge" in caplog.text
    assert "/challenge" in caplog.text


def test_healthy_traffic_is_processed_silently(local_server, caplog):
    analyzer = get_analyzer()
    watched = wrap(requests.Session(), job="ebay-prices")
    before = analyzer.processed_events

    with caplog.at_level(logging.WARNING, logger="scrapewatch"):
        watched.get(local_server)
        analyzer.flush()

    assert analyzer.processed_events == before + 1
    assert "blocked" not in caplog.text  # ok verdicts stay at DEBUG


def test_transport_failure_becomes_an_event_and_reraises(local_server):
    analyzer = get_analyzer()
    watched = wrap(requests.Session(), job="ebay-prices")
    before = analyzer.processed_events

    with pytest.raises(requests.exceptions.ConnectionError):
        watched.get("http://127.0.0.1:1/nope")

    analyzer.flush()
    assert analyzer.processed_events == before + 1


def test_killing_the_analyzer_leaves_the_scraper_unaffected(local_server):
    # roadmap Phase 2 gate: the analyzer dies mid-run, requests keep working
    analyzer = get_analyzer()
    watched = wrap(requests.Session(), job="ebay-prices")

    analyzer.stop()  # worker thread is gone; the queue just accumulates

    response = watched.get(local_server)

    assert response.status_code == 200
    assert response.text == "<html>prices</html>"
    assert watched._scrapewatch_seen == 1

    analyzer._ensure_thread()  # revive the singleton for later tests
    analyzer.flush()
