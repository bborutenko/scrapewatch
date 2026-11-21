"""Event dataclass: contract shape, immutability, round-trip, conventions."""

import dataclasses

import pytest

from scrapewatch.core.event import (
    SCHEMA_VERSION,
    Event,
    JobRef,
)


def _event(**overrides) -> Event:
    defaults = {
        "url": "https://example.com/prices",
        "job": JobRef(name="ebay-prices", run_id="run-1"),
        "captured_at": "2026-11-15T00:00:00+00:00",
    }
    return Event(**(defaults | overrides))


def test_required_trio_has_no_defaults():
    with pytest.raises(TypeError):
        Event()


def test_defaults_match_the_contract_table():
    event = _event()
    assert event.schema_version == SCHEMA_VERSION == 1
    assert event.method == "GET"
    assert event.status_code is None
    assert event.headers == {}
    assert event.content_type is None
    assert event.body_sample == ""
    assert event.body_hash is None
    assert event.body_length is None
    assert event.latency_ms is None
    assert event.items is None
    assert event.meta == {}


def test_run_id_is_always_explicit():
    with pytest.raises(TypeError):
        JobRef(name="ebay-prices")  # type: ignore[call-arg]


def test_events_are_immutable():
    event = _event()
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.url = "https://other.example.com"  # type: ignore[misc]


def test_to_dict_is_an_independent_snapshot():
    event = _event(headers={"x-job": "1"}, meta={"redirects": 2})
    snapshot = event.to_dict()

    snapshot["headers"]["x-injected"] = "1"
    snapshot["meta"]["redirects"] = 99

    assert event.headers == {"x-job": "1"}
    assert event.meta == {"redirects": 2}


def test_round_trip_preserves_every_field():
    event = _event(
        status_code=403,
        headers={"content-type": "text/html"},
        content_type="text/html",
        body_sample="<html>challenge</html>",
        body_hash="ab" * 32,
        body_length=21,
        latency_ms=123.4,
        items=[{"price": ""}],
        meta={"redirects": 1},
    )

    assert Event.from_dict(event.to_dict()) == event


def test_from_dict_fails_loudly_on_unknown_keys():
    with pytest.raises(TypeError):
        Event.from_dict({**_event().to_dict(), "future_field": 1})
