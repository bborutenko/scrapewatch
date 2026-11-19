"""Verdict — the engine's judgment about one Event.

The field-by-field source of truth is docs/contracts/interfaces.md
Part A.2; this module is its Python form. A verdict is the printed
judgment, not the judge: the engine (core/engine.py) builds it from the
rules that fired, and it carries no rule logic itself. Validation lives
in tests against the contract, not at runtime (as in event.py).
"""

import dataclasses
import enum
from collections.abc import Sequence
from typing import Any

__all__ = ["PRECEDENCE", "Severity", "Status", "Verdict", "aggregate"]


class Status(enum.StrEnum):
    """Classification outcomes, contract A.2; definitions in CONCEPTS.md."""

    OK = "ok"  # the response looks like the real page and the data looks healthy
    BLOCKED = "blocked"  # anti-bot artifact: challenge page, captcha wall, access denied — whatever the HTTP status
    GARBAGE = "garbage"  # technically a page but not the expected one: SPA shell, login wall, geo-block, soft-404
    DRIFTED = "drifted"  # page renders fine but the data shape changed; mostly job-level aggregation (Phase 3)
    UNKNOWN = "unknown"  # scrapewatch's own analysis failed: unclassified, never an error (ADR-8)


class Severity(enum.IntEnum):
    """Detector weight for multi-match conflicts (A.2): highest wins.

    IntEnum on purpose — "highest severity wins" is then a plain max().
    """

    LOW = 1
    MEDIUM = 2
    HIGH = 3


#: Tie-break order when severities are equal (A.2): "ties broken by
#: verdict precedence blocked > garbage > drifted > ok". UNKNOWN never
#: competes — it is a degradation, not a candidate.
PRECEDENCE: tuple[Status, ...] = (
    Status.BLOCKED,
    Status.GARBAGE,
    Status.DRIFTED,
    Status.OK,
)


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class Verdict:
    """The engine's judgment about one Event, contract A.2.

    Fields follow the contract table order; every field is required by
    the contract, so none has a default — use the ``ok``/``unknown``
    factories for the two verdicts callers build by hand.
    """

    status: Status
    detector_id: str | None  # rule that fired; "schema" for item validation; None for ok
    reason: str  # human-readable one-liner, e.g. "Cloudflare interstitial behind HTTP 200"
    confidence: float  # 0.0–1.0, from the matched-signature share (C.3.4); 1.0 for ok
    # evidence is a plain dict: read-only by convention, not by force —
    # the convention is pinned by tests (as in event.py)
    evidence: dict[str, Any]  # machine-readable match details: signatures that fired
    event_hash: str  # sha256 of the canonical JSON of the source Event (A.2)

    @classmethod
    def ok(cls, *, event_hash: str) -> "Verdict":
        """Nothing fired: the response looks like the real page.

        ``confidence`` is 1.0 — no signatures are involved, so there is
        no doubt to measure (pinned in interfaces.md A.2).
        """
        return cls(
            status=Status.OK,
            detector_id=None,
            reason="no detector fired",
            confidence=1.0,
            evidence={},
            event_hash=event_hash,
        )

    @classmethod
    def unknown(cls, *, reason: str, event_hash: str) -> "Verdict":
        """Scrapewatch's own analysis failed: degrade, never raise (ADR-8)."""
        return cls(
            status=Status.UNKNOWN,
            detector_id=None,
            reason=reason,
            confidence=0.0,
            evidence={},
            event_hash=event_hash,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serializable snapshot; ``status`` as its plain contract string."""
        data = dataclasses.asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Verdict":
        """Rebuild a Verdict from its serialized form (storage round-trip).

        Unknown keys raise ``TypeError`` — the same loud-failure
        convention as ``Event.from_dict``.
        """
        payload = dict(data)
        payload["status"] = Status(payload["status"])
        return cls(**payload)


def aggregate(candidates: Sequence[tuple[Severity, Verdict]]) -> Verdict:
    """Winner of a multi-match event (A.2): highest severity, ties by PRECEDENCE.

    Severity is a detector attribute, not a Verdict field, so each
    candidate travels as a ``(severity, verdict)`` pair. Empty input is
    a caller bug: "nothing fired" is ``Verdict.ok``, decided by the
    engine before it ever aggregates. An ``unknown`` candidate is also
    a bug — unknown is a degradation, never an aggregation input.
    """
    if not candidates:
        raise ValueError("aggregate() needs at least one candidate; 'nothing fired' is Verdict.ok()")

    rank = {status: -position for position, status in enumerate(PRECEDENCE)}
    _, winner = max(candidates, key=lambda pair: (pair[0], rank[pair[1].status]))
    return winner
