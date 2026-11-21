"""WatchedSession: state carryover and the capture hook, without a network."""

import requests
from requests.adapters import HTTPAdapter

import scrapewatch as sw


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
    watched = sw.watch(original, job="ebay-prices")

    assert watched is not original
    assert isinstance(watched, requests.Session)
    assert watched.headers["X-Job"] == "ebay-prices"
    assert isinstance(watched.get_adapter("https://example.com"), _StaticAdapter)


def test_cookies_survive_the_wrap():
    original = _configured_session()
    original.cookies.set("session-id", "42")

    assert sw.watch(original, job="ebay-prices").cookies.get("session-id") == "42"


def test_every_response_passes_the_capture_hook():
    watched = sw.watch(_configured_session(), job="ebay-prices")

    for _ in range(3):
        assert watched.get("https://example.com/prices").status_code == 200

    assert watched._scrapewatch_seen == 3


def test_each_wrap_gets_its_own_run_id():
    # contract A.1: run_id is explicit, one run per wrap()
    first = sw.watch(_configured_session(), job="ebay-prices")
    second = sw.watch(_configured_session(), job="ebay-prices")

    assert first._scrapewatch_jobref.name == "ebay-prices"
    assert first._scrapewatch_jobref.run_id != second._scrapewatch_jobref.run_id


def test_invalid_custom_rules_fail_loudly_at_wrap_time(tmp_path):
    # C.3.5: a broken rule file is a setup-time error, not a mid-scrape surprise
    import pytest

    from scrapewatch.core.rules import RuleLoadError

    broken = tmp_path / "bad.yaml"
    broken.write_text(
        "id: bad\nname: Bad\nverdict: blocked\nseverity: high\n"
        "match:\n  any_of:\n    - body_re: ['[']\n",
        encoding="utf-8",
    )

    with pytest.raises(RuleLoadError):
        sw.watch(_configured_session(), job="ebay-prices", rules=[broken])


def test_custom_rules_replace_the_engine_per_session(tmp_path):
    custom = tmp_path / "custom.yaml"
    custom.write_text(
        "id: my-marker\nname: My marker\nverdict: garbage\nseverity: medium\n"
        "match:\n  any_of:\n    - body_re: ['prices']\n",
        encoding="utf-8",
    )

    watched = sw.watch(_configured_session(), job="ebay-prices", rules=[custom])

    assert watched._scrapewatch_engine is not None
    rule_ids = {rule.id for rule in watched._scrapewatch_engine._rules}
    assert "my-marker" in rule_ids


def test_analyzer_and_engine_are_set():
    """Wrapped session has analyzer and engine set."""
    watched = sw.watch(_configured_session(), job="ebay-prices")

    assert watched._scrapewatch_analyzer is not None
    assert watched._scrapewatch_engine is not None
