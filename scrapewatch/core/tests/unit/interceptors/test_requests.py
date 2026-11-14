"""WatchedSession: state carryover and the capture hook, without a network."""

import requests
from requests.adapters import HTTPAdapter

from scrapewatch.interceptors.requests_interceptor import wrap


class _StaticAdapter(HTTPAdapter):
    """Returns a canned 200 without touching the network."""

    def send(self, request, **kwargs):
        response = requests.Response()
        response.status_code = 200
        response.request = request
        response._content = b"<html>prices</html>"
        return response


def _configured_session() -> requests.Session:
    session = requests.Session()
    session.headers["X-Job"] = "ebay-prices"
    session.mount("https://", _StaticAdapter())
    return session


def test_wrap_returns_a_new_equivalent_session():
    original = _configured_session()
    watched = wrap(original, job="ebay-prices")

    assert watched is not original
    assert isinstance(watched, requests.Session)
    assert watched.headers["X-Job"] == "ebay-prices"
    assert isinstance(watched.get_adapter("https://example.com"), _StaticAdapter)


def test_cookies_survive_the_wrap():
    original = _configured_session()
    original.cookies.set("session-id", "42")

    assert wrap(original, job="ebay-prices").cookies.get("session-id") == "42"


def test_every_response_passes_the_capture_hook():
    watched = wrap(_configured_session(), job="ebay-prices")

    for _ in range(3):
        assert watched.get("https://example.com/prices").status_code == 200

    assert watched._scrapewatch_seen == 3
