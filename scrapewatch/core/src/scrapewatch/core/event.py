"""Event — one observed HTTP response, the unit of the data contract.

The field-by-field source of truth is docs/contracts/interfaces.md
Part A.1; this module is its Python form. Events are immutable facts:
built exclusively by interceptors, consumed exclusively by the engine
(ADR-2). Validation lives in tests against the contract schema, not
at runtime.
"""

import dataclasses
from typing import Any

#: Event contract version; bumps only incompatibly, with an ADR (A.3).
SCHEMA_VERSION = 1


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class JobRef:
    """Which job an event belongs to — storage aggregates by this identity.

    ``run_id`` is created once per ``watch()`` call and passed explicitly;
    the schema itself is registered on the job, not repeated per event.
    """

    name: str
    run_id: str
    schema_id: str | None = None


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class Event:
    """One observed HTTP response (or browser navigation), contract A.1."""

    # required by the contract
    url: str
    job: JobRef
    captured_at: str  # ISO-8601 UTC, set by the interceptor at capture time

    # optional by the contract, in table order
    schema_version: int = SCHEMA_VERSION
    method: str = "GET"
    status_code: int | None = None  # None: the transport never got a response
    # headers/meta are plain dicts: read-only by convention, not by force —
    # the convention is pinned by tests (to_dict must not alias them)
    headers: dict[str, str] = dataclasses.field(default_factory=dict)  # keys lowercase
    content_type: str | None = None  # content-type without charset
    body_sample: str = ""  # decoded body prefix; the only body detectors may inspect
    body_hash: str | None = None  # sha256 of the full raw body
    body_length: int | None = None
    latency_ms: float | None = None
    items: list[dict[str, object]] | None = None  # user records for schema validation
    meta: dict[str, object] = dataclasses.field(default_factory=dict)  # interceptor extras

    def to_dict(self) -> dict[str, Any]:
        """Serializable snapshot; deep-copied, so mutating it cannot touch the event."""
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Event":
        """Rebuild an Event from its serialized form (storage round-trip).

        Unknown keys raise ``TypeError``: an event from a newer contract
        version must fail loudly, not silently lose fields.
        """
        payload = dict(data)
        payload["job"] = JobRef(**payload.pop("job"))
        return cls(**payload)
