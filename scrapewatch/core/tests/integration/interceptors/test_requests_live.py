"""WatchedSession against a real local HTTP server: sockets, redirects, cookies."""

import requests

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
