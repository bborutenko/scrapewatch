"""Engine.observe: pipeline, confidence formula (C.3.4), aggregation, never-raise."""

import hashlib
import json

import pytest

from scrapewatch.core.engine import Engine
from scrapewatch.core.event import Event, JobRef
from scrapewatch.core.rules import load_rule_file, load_rules
from scrapewatch.core.verdict import Status

FAKE_200 = (
    "<html><head><title>Just a moment...</title></head>"
    "<body><p>Checking your browser before accessing</p></body></html>"
)
HEALTHY = (
    "<html><head><title>Shop — iPhone prices</title></head>"
    "<body><div class='product'>iPhone 15 — $999</div>"
    "<script src='/static/bundle.js'></script></body></html>"
)


def _event(**overrides) -> Event:
    defaults = {
        "url": "https://example.com/listing",
        "job": JobRef(name="ebay-prices", run_id="run-1"),
        "captured_at": "2026-11-19T00:00:00+00:00",
        "status_code": 200,
        "headers": {"content-type": "text/html"},
        "body_sample": HEALTHY,
    }
    return Event(**(defaults | overrides))


def _engine(tmp_path, yaml_text, name="rule.yaml") -> Engine:
    path = tmp_path / name
    path.write_text(yaml_text, encoding="utf-8")
    return Engine(load_rule_file(path))


# --- the product's reason to exist -----------------------------------------


def test_healthy_page_is_ok():
    verdict = Engine(load_rules()).observe(_event())

    assert verdict.status is Status.OK
    assert verdict.detector_id is None
    assert verdict.confidence == 1.0


def test_challenge_page_behind_http_200_is_blocked_not_ok():
    verdict = Engine(load_rules()).observe(_event(body_sample=FAKE_200, status_code=200))

    assert verdict.status is Status.BLOCKED
    assert verdict.detector_id == "cloudflare-challenge"
    assert "behind HTTP 200" in verdict.reason


def test_confidence_follows_the_c34_formula(tmp_path):
    # one fired group, one matched primitive: 0.5 + 0.5*1 = 1.0,
    # status 200 disagrees with the hint [403, 429, 503]: -0.1
    verdict = Engine(load_rules()).observe(_event(body_sample=FAKE_200, status_code=200))

    assert verdict.confidence == pytest.approx(0.9)
    assert verdict.evidence["matched_primitives"] == 1
    assert verdict.evidence["total_primitives"] == 1
    assert verdict.evidence["matched_signatures"] == ["title_re: Just a moment"]


def test_status_hint_agreement_caps_confidence_at_one():
    verdict = Engine(load_rules()).observe(_event(body_sample=FAKE_200, status_code=403))

    assert verdict.confidence == 1.0  # 1.0 + 0.1, capped (C.3.4)


def test_reason_names_the_http_status_when_not_200():
    verdict = Engine(load_rules()).observe(_event(body_sample=FAKE_200, status_code=403))
    assert verdict.reason.endswith("(HTTP 403)")

    no_response = Engine(load_rules()).observe(_event(body_sample=FAKE_200, status_code=None))
    assert "no response received" in no_response.reason


# --- correlation ------------------------------------------------------------


def test_event_hash_is_the_canonical_fingerprint():
    event = _event()
    verdict = Engine(load_rules()).observe(event)

    canonical = json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":"), default=str)
    assert verdict.event_hash == hashlib.sha256(canonical.encode()).hexdigest()


def test_same_event_hashes_the_same_across_verdicts():
    event = _event(body_sample=FAKE_200)
    engine = Engine(load_rules())

    assert engine.observe(event).event_hash == engine.observe(event).event_hash
    assert engine.observe(event).event_hash != engine.observe(_event(url="https://other.example.com")).event_hash


# --- rule semantics ---------------------------------------------------------

SAME_MARKER_RULES = r"""
id: marker-low
name: Low marker
verdict: garbage
severity: low
match:
  any_of:
    - body_re: ["TEST-MARKER"]
---
id: marker-high
name: High marker
verdict: blocked
severity: high
match:
  any_of:
    - body_re: ["TEST-MARKER"]
"""

ALL_OF_RULE = r"""
id: needs-both
name: Needs both signals
verdict: garbage
severity: medium
match:
  all_of:
    - header:
        Server: '^cloudflare$'
    - body_re:
        - "TEST-MARKER"
"""


def test_highest_severity_wins_when_several_detectors_fire(tmp_path):
    engine = _engine(tmp_path, SAME_MARKER_RULES)
    verdict = engine.observe(_event(body_sample="<p>TEST-MARKER</p>"))

    assert verdict.status is Status.BLOCKED
    assert verdict.detector_id == "marker-high"


def test_all_of_fires_only_when_every_group_matches(tmp_path):
    engine = _engine(tmp_path, ALL_OF_RULE)

    both = engine.observe(_event(headers={"server": "cloudflare"}, body_sample="<p>TEST-MARKER</p>"))
    assert both.status is Status.GARBAGE
    assert both.detector_id == "needs-both"

    body_only = engine.observe(_event(body_sample="<p>TEST-MARKER</p>"))
    assert body_only.status is Status.OK

    header_only = engine.observe(_event(headers={"server": "cloudflare"}, body_sample="<html></html>"))
    assert header_only.status is Status.OK


def test_engine_without_rules_always_says_ok():
    assert Engine(rules=[]).observe(_event(body_sample=FAKE_200)).status is Status.OK


# --- failure policy (ADR-6, ADR-8) -------------------------------------------


def test_observe_never_raises_and_degrades_to_unknown(monkeypatch):
    engine = Engine(load_rules())

    def explode(*args, **kwargs):
        raise RuntimeError("detector exploded")

    monkeypatch.setattr(engine, "_classify", explode)

    verdict = engine.observe(_event())

    assert verdict.status is Status.UNKNOWN
    assert "detector exploded" in verdict.reason
    assert engine.failures == 1


def test_a_clean_run_keeps_the_failure_counter_at_zero():
    engine = Engine(load_rules())
    engine.observe(_event(body_sample=FAKE_200))
    assert engine.failures == 0
