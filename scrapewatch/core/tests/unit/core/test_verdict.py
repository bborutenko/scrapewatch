"""Verdict + aggregation rule: contract A.2 pinned by tests."""

import dataclasses

import pytest

from scrapewatch.core.verdict import PRECEDENCE, Severity, Status, Verdict, aggregate


def _verdict(status=Status.BLOCKED, **overrides) -> Verdict:
    defaults = {
        "status": status,
        "detector_id": "cloudflare-challenge",
        "reason": "Cloudflare interstitial behind HTTP 200",
        "confidence": 0.9,
        "evidence": {"matched_signatures": ["title_re: Just a moment"]},
        "event_hash": "ab" * 32,
    }
    return Verdict(**(defaults | overrides))


def test_status_values_match_the_contract():
    assert {status.value for status in Status} == {"ok", "blocked", "garbage", "drifted", "unknown"}


def test_severity_ordering_is_max_compatible():
    assert Severity.LOW < Severity.MEDIUM < Severity.HIGH
    assert max(Severity.LOW, Severity.HIGH) is Severity.HIGH


def test_precedence_is_the_contract_tie_break():
    assert PRECEDENCE == (Status.BLOCKED, Status.GARBAGE, Status.DRIFTED, Status.OK)
    assert Status.UNKNOWN not in PRECEDENCE  # degradation, not a candidate


def test_every_contract_field_is_required():
    with pytest.raises(TypeError):
        Verdict()  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        Verdict(status=Status.OK)  # type: ignore[call-arg]


def test_verdicts_are_immutable():
    verdict = _verdict()
    with pytest.raises(dataclasses.FrozenInstanceError):
        verdict.status = Status.OK  # type: ignore[misc]


def test_to_dict_serializes_status_as_a_plain_string():
    data = _verdict().to_dict()
    assert data["status"] == "blocked"
    assert type(data["status"]) is str


def test_to_dict_is_an_independent_snapshot():
    verdict = _verdict()
    snapshot = verdict.to_dict()

    snapshot["evidence"]["matched_signatures"].append("injected")

    assert verdict.evidence["matched_signatures"] == ["title_re: Just a moment"]


def test_round_trip_preserves_every_field():
    verdict = _verdict(
        status=Status.GARBAGE,
        detector_id="soft-404",
        reason="Soft 404 (HTTP 200)",
        confidence=0.6,
        evidence={"matched_signatures": [], "matched_primitives": 0, "total_primitives": 1},
        event_hash="cd" * 32,
    )
    assert Verdict.from_dict(verdict.to_dict()) == verdict


def test_from_dict_fails_loudly_on_unknown_keys():
    with pytest.raises(TypeError):
        Verdict.from_dict({**_verdict().to_dict(), "future_field": 1})


def test_ok_factory_follows_the_contract():
    verdict = Verdict.ok(event_hash="ab" * 32)
    assert verdict.status is Status.OK
    assert verdict.detector_id is None
    assert verdict.confidence == 1.0  # pinned in interfaces.md A.2
    assert verdict.evidence == {}


def test_unknown_factory_carries_the_reason():
    verdict = Verdict.unknown(reason="analysis failed: boom", event_hash="ab" * 32)
    assert verdict.status is Status.UNKNOWN
    assert verdict.detector_id is None
    assert verdict.confidence == 0.0
    assert "boom" in verdict.reason


def test_aggregate_highest_severity_wins_over_precedence():
    low_blocked = _verdict(Status.BLOCKED, detector_id="low-block")
    high_garbage = _verdict(Status.GARBAGE, detector_id="high-garbage")
    winner = aggregate([(Severity.LOW, low_blocked), (Severity.HIGH, high_garbage)])
    assert winner is high_garbage


def test_aggregate_ties_break_by_precedence():
    blocked = _verdict(Status.BLOCKED)
    garbage = _verdict(Status.GARBAGE)
    assert aggregate([(Severity.HIGH, garbage), (Severity.HIGH, blocked)]) is blocked
    assert aggregate([(Severity.HIGH, blocked), (Severity.HIGH, garbage)]) is blocked


def test_aggregate_returns_the_candidate_itself():
    verdict = _verdict()
    assert aggregate([(Severity.MEDIUM, verdict)]) is verdict


def test_aggregate_refuses_empty_input():
    with pytest.raises(ValueError, match="Verdict.ok"):
        aggregate([])
