import pytest

from scrapewatch.core.engine import Engine
from scrapewatch.core.event import Event, JobRef
from scrapewatch.core.rules import load_rule_file, load_rules
from scrapewatch.core.verdict import Status

CLOUDFLARE_RULE = """
id: cloudflare-challenge
name: Cloudflare challenge / interstitial
verdict: blocked
severity: high
match:
  status_hint: [403, 429, 503]
  any_of:
    - title_re: ["Just a moment..."]
    - body_re: ["cdn-cgi/challenge-platform"]
"""

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


def _cloudflare_engine(tmp_path) -> Engine:
    return _engine(tmp_path, CLOUDFLARE_RULE)


def test_healthy_page_is_ok():
    verdict = Engine(load_rules()).observe(_event())

    assert verdict.status is Status.OK
    assert verdict.detector_id is None
    assert verdict.confidence == 1.0


def test_challenge_page_behind_http_200_is_blocked_not_ok(tmp_path):
    verdict = _cloudflare_engine(tmp_path).observe(_event(body_sample=FAKE_200, status_code=200))

    assert verdict.status is Status.BLOCKED
    assert verdict.detector_id == "cloudflare-challenge"
    assert "behind HTTP 200" in verdict.reason


def test_confidence_follows_the_c34_formula(tmp_path):
    verdict = _cloudflare_engine(tmp_path).observe(_event(body_sample=FAKE_200, status_code=200))

    assert verdict.confidence == pytest.approx(0.9)
    assert verdict.evidence["matched_primitives"] == 1
    assert verdict.evidence["total_primitives"] == 1
    assert verdict.evidence["matched_signatures"] == ["title_re: Just a moment..."]


def test_status_hint_agreement_caps_confidence_at_one(tmp_path):
    verdict = _cloudflare_engine(tmp_path).observe(_event(body_sample=FAKE_200, status_code=403))

    assert verdict.confidence == 1.0


def test_reason_names_the_http_status_when_not_200(tmp_path):
    verdict = _cloudflare_engine(tmp_path).observe(_event(body_sample=FAKE_200, status_code=403))
    assert verdict.reason.endswith("(HTTP 403)")
