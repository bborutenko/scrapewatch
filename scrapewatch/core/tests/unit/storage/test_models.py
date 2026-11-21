"""Storage models: Run, Aggregate dataclass tests.

Tests cover:
- Run factory method and finish method
- Aggregate factory method
- Immutability (frozen dataclasses)
- Field validation
"""

import dataclasses

import pytest

from scrapewatch.storage.models import Aggregate, Run



class TestRun:
    """Run dataclass: creation, finishing, immutability."""

    def test_create_factory_sets_required_fields(self):
        """Run.create sets id, job, and started_at."""
        run = Run.create(run_id="run-001", job="ebay-prices")

        assert run.id == "run-001"
        assert run.job == "ebay-prices"
        assert run.started_at is not None
        assert run.ended_at is None
        assert run.events == 0
        assert run.analyzer_errors == 0

    def test_create_sets_iso8601_timestamp(self):
        """Run.create sets valid ISO-8601 timestamp."""
        run = Run.create(run_id="run-001", job="test")

        # Should be parseable as ISO-8601
        from datetime import datetime

        dt = datetime.fromisoformat(run.started_at)
        assert dt is not None

    def test_create_sets_utc_timezone(self):
        """Run.create sets UTC timezone."""
        run = Run.create(run_id="run-001", job="test")

        # ISO-8601 with timezone
        assert run.started_at.endswith("+00:00") or "Z" in run.started_at

    def test_finish_sets_ended_at(self):
        """Run.finish sets ended_at timestamp."""
        run = Run.create(run_id="run-001", job="test")
        finished = run.finish(events=100, analyzer_errors=2)

        assert finished.ended_at is not None
        assert run.ended_at is None  # Original is unchanged

    def test_finish_sets_events_and_errors(self):
        """Run.finish sets event counts."""
        run = Run.create(run_id="run-001", job="test")
        finished = run.finish(events=500, analyzer_errors=3)

        assert finished.events == 500
        assert finished.analyzer_errors == 3
        assert run.events == 0  # Original is unchanged

    def test_finish_preserves_id_and_job(self):
        """Run.finish preserves identity."""
        run = Run.create(run_id="run-001", job="ebay-prices")
        finished = run.finish(events=0, analyzer_errors=0)

        assert finished.id == "run-001"
        assert finished.job == "ebay-prices"

    def test_run_is_immutable(self):
        """Run is frozen (immutable)."""
        run = Run.create(run_id="run-001", job="test")

        with pytest.raises(dataclasses.FrozenInstanceError):
            run.events = 100  # type: ignore[misc]

    def test_run_direct_construction(self):
        """Run can be constructed directly with all fields."""
        from datetime import datetime, timezone

        run = Run(
            id="run-001",
            job="test",
            started_at=datetime.now(timezone.utc).isoformat(),
            ended_at=None,
            events=0,
            analyzer_errors=0,
        )

        assert run.id == "run-001"

    def test_run_with_ended_at(self):
        """Run can have ended_at set."""
        from datetime import datetime, timezone

        run = Run(
            id="run-001",
            job="test",
            started_at="2026-11-21T00:00:00+00:00",
            ended_at="2026-11-21T01:00:00+00:00",
            events=100,
            analyzer_errors=0,
        )

        assert run.ended_at == "2026-11-21T01:00:00+00:00"



class TestAggregate:
    """Aggregate dataclass: creation, immutability."""

    def test_create_factory_sets_all_fields(self):
        """Aggregate.create sets job, key, value, and updated_at."""
        agg = Aggregate.create(job="ebay-prices", key="fill_rate", value={"price": 0.95})

        assert agg.job == "ebay-prices"
        assert agg.key == "fill_rate"
        assert agg.value == {"price": 0.95}
        assert agg.updated_at is not None

    def test_create_sets_iso8601_timestamp(self):
        """Aggregate.create sets valid ISO-8601 timestamp."""
        agg = Aggregate.create(job="test", key="stats", value={})

        from datetime import datetime

        dt = datetime.fromisoformat(agg.updated_at)
        assert dt is not None

    def test_create_sets_utc_timezone(self):
        """Aggregate.create sets UTC timezone."""
        agg = Aggregate.create(job="test", key="stats", value={})

        assert agg.updated_at.endswith("+00:00") or "Z" in agg.updated_at

    def test_aggregate_is_immutable(self):
        """Aggregate is frozen (immutable)."""
        agg = Aggregate.create(job="test", key="stats", value={"count": 1})

        with pytest.raises(dataclasses.FrozenInstanceError):
            agg.value = {"count": 2}  # type: ignore[misc]

    def test_aggregate_with_complex_value(self):
        """Aggregate can store nested structures."""
        value = {
            "fill_rates": {"price": 0.95, "title": 1.0, "image": 0.87},
            "drift_status": "ok",
            "last_ok": "2026-11-21T00:00:00+00:00",
            "metrics": {"total_events": 1000, "blocked": 5, "garbage": 2},
        }
        agg = Aggregate.create(job="ebay-prices", key="quality", value=value)

        assert agg.value["fill_rates"]["price"] == 0.95
        assert agg.value["metrics"]["blocked"] == 5

    def test_aggregate_direct_construction(self):
        """Aggregate can be constructed directly."""
        from datetime import datetime, timezone

        agg = Aggregate(
            job="test",
            key="stats",
            value={"count": 10},
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

        assert agg.job == "test"
        assert agg.key == "stats"

    def test_aggregate_value_is_dict(self):
        """Aggregate value is always a dict."""
        agg = Aggregate.create(job="test", key="empty", value={})
        assert isinstance(agg.value, dict)

        agg2 = Aggregate.create(job="test", key="nested", value={"a": {"b": {"c": 1}}})
        assert isinstance(agg2.value, dict)



class TestDataclassFeatures:
    """Python dataclass features: slots, equality, etc."""

    def test_run_equality(self):
        """Run instances with same fields are equal."""
        run1 = Run(
            id="run-001",
            job="test",
            started_at="2026-11-21T00:00:00+00:00",
        )
        run2 = Run(
            id="run-001",
            job="test",
            started_at="2026-11-21T00:00:00+00:00",
        )

        assert run1 == run2

    def test_run_inequality(self):
        """Run instances with different fields are not equal."""
        run1 = Run.create(run_id="run-001", job="test")
        run2 = Run.create(run_id="run-002", job="test")

        assert run1 != run2

    def test_aggregate_equality(self):
        """Aggregate instances with same fields are equal."""
        agg1 = Aggregate(
            job="test",
            key="stats",
            value={"count": 1},
            updated_at="2026-11-21T00:00:00+00:00",
        )
        agg2 = Aggregate(
            job="test",
            key="stats",
            value={"count": 1},
            updated_at="2026-11-21T00:00:00+00:00",
        )

        assert agg1 == agg2

    def test_run_has_slots(self):
        """Run uses __slots__ for memory efficiency."""
        run = Run.create(run_id="run-001", job="test")
        # With slots, __dict__ should not exist
        assert not hasattr(run, "__dict__")

    def test_aggregate_has_slots(self):
        """Aggregate uses __slots__ for memory efficiency."""
        agg = Aggregate.create(job="test", key="stats", value={})
        assert not hasattr(agg, "__dict__")

    def test_run_repr_is_descriptive(self):
        """Run repr includes key fields."""
        run = Run.create(run_id="run-001", job="ebay-prices")
        repr_str = repr(run)

        assert "run-001" in repr_str
        assert "ebay-prices" in repr_str

    def test_aggregate_repr_is_descriptive(self):
        """Aggregate repr includes key fields."""
        agg = Aggregate.create(job="test", key="stats", value={})
        repr_str = repr(agg)

        assert "test" in repr_str
        assert "stats" in repr_str
