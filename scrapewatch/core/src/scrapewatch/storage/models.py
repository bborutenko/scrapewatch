"""Data models for storage layer: Run, EventRecord, Aggregate."""

import dataclasses
from datetime import datetime, timezone


@dataclasses.dataclass(frozen=True, slots=True)
class Run:
    """One scraping run: tracks events count and errors."""

    id: str
    job: str
    started_at: str
    ended_at: str | None = None
    events: int = 0
    analyzer_errors: int = 0

    @classmethod
    def create(cls, run_id: str, job: str) -> "Run":
        """Factory for a new run."""
        return cls(
            id=run_id,
            job=job,
            started_at=datetime.now(timezone.utc).isoformat(),
        )

    def finish(self, events: int, analyzer_errors: int) -> "Run":
        """Return a new Run with ended_at set."""
        return dataclasses.replace(
            self,
            ended_at=datetime.now(timezone.utc).isoformat(),
            events=events,
            analyzer_errors=analyzer_errors,
        )


@dataclasses.dataclass(frozen=True, slots=True)
class Aggregate:
    """Job-level aggregate: fill rate, drift state, freshness."""

    job: str
    key: str
    value: dict
    updated_at: str

    @classmethod
    def create(cls, job: str, key: str, value: dict) -> "Aggregate":
        """Factory for a new aggregate."""
        return Aggregate(
            job=job,
            key=key,
            value=value,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
