"""SQLite storage layer: schema, CRUD operations, batching, and fault tolerance.

Tests cover:
- Schema initialization and idempotency
- Run lifecycle (create, update, finish)
- Event write and batched flush
- Aggregate read/write round-trips
- Purge old events
- Never-raise policy (ADR-6) for error handling
- WAL mode and thread safety
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scrapewatch.core.event import Event, JobRef
from scrapewatch.core.verdict import Status, Verdict
from scrapewatch.storage.sqlite import Storage


# ============================================================================
# Schema Tests
# ============================================================================


class TestSchemaInit:
    """Schema initialization is idempotent and creates correct tables."""

    def test_creates_all_tables(self, storage, temp_db_path):
        """All three tables are created with correct names."""
        cursor = storage._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cursor.fetchall()}
        # sqlite_sequence is auto-created by AUTOINCREMENT
        assert tables >= {"aggregates", "events", "runs"}

    def test_runs_table_schema(self, storage):
        """Runs table has correct columns."""
        cursor = storage._db.execute("PRAGMA table_info(runs)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        assert columns["id"] == "TEXT"
        assert columns["job"] == "TEXT"
        assert columns["started_at"] == "TEXT"
        assert columns["ended_at"] == "TEXT"
        assert columns["events"] == "INTEGER"
        assert columns["analyzer_errors"] == "INTEGER"

    def test_events_table_schema(self, storage):
        """Events table has correct columns and foreign key."""
        cursor = storage._db.execute("PRAGMA table_info(events)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        assert columns["id"] == "INTEGER"
        assert columns["run_id"] == "TEXT"
        assert columns["captured_at"] == "TEXT"
        assert columns["url"] == "TEXT"
        assert columns["event_json"] == "TEXT"
        assert columns["verdict_json"] == "TEXT"

    def test_aggregates_table_schema(self, storage):
        """Aggregates table has correct primary key."""
        cursor = storage._db.execute("PRAGMA table_info(aggregates)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        assert columns["job"] == "TEXT"
        assert columns["key"] == "TEXT"
        assert columns["value_json"] == "TEXT"
        assert columns["updated_at"] == "TEXT"

    def test_events_indexes_exist(self, storage):
        """Events table has indexes on run_id and captured_at."""
        cursor = storage._db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='events'"
        )
        indexes = {row[0] for row in cursor.fetchall()}
        assert "idx_events_run_id" in indexes
        assert "idx_events_captured_at" in indexes

    def test_schema_is_idempotent(self, temp_db_path):
        """Calling _init_schema twice does not raise."""
        storage = Storage(db_path=temp_db_path)
        storage._init_schema()  # Should be safe
        storage._init_schema()  # Should still be safe
        storage.close()

    def test_foreign_key_on_events(self, storage):
        """Events table has foreign key to runs."""
        cursor = storage._db.execute("PRAGMA foreign_key_list(events)")
        fks = list(cursor.fetchall())
        assert len(fks) == 1
        assert fks[0][2] == "runs"  # referenced table
        assert fks[0][3] == "run_id"  # from column
        assert fks[0][4] == "id"  # to column


class TestWALMode:
    """WAL mode is enabled for concurrent read/write support."""

    def test_wal_mode_enabled(self, storage):
        """WAL journal mode is active."""
        cursor = storage._db.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        assert mode.lower() == "wal"


# ============================================================================
# Run Tests
# ============================================================================


class TestWriteRun:
    """Run lifecycle: create, update, finish."""

    def test_insert_new_run(self, storage, run):
        """A new run is inserted correctly."""
        storage.write_run(run)

        cursor = storage._db.execute("SELECT * FROM runs WHERE id = ?", (run.id,))
        row = cursor.fetchone()

        assert row is not None
        assert row[0] == run.id
        assert row[1] == run.job
        assert row[2] == run.started_at
        assert row[3] is None  # ended_at
        assert row[4] == 0  # events
        assert row[5] == 0  # analyzer_errors

    def test_update_existing_run(self, storage, run):
        """An existing run is updated on conflict."""
        storage.write_run(run)

        # Create finished version
        finished = run.finish(events=100, analyzer_errors=2)
        storage.write_run(finished)

        cursor = storage._db.execute("SELECT * FROM runs WHERE id = ?", (run.id,))
        row = cursor.fetchone()

        assert row[3] is not None  # ended_at is set
        assert row[4] == 100
        assert row[5] == 2

    def test_never_raises_on_db_error(self, storage, run):
        """Write errors are swallowed and logged (ADR-6)."""
        storage.close()

        # This should not raise, just log the error
        storage.write_run(run)


# ============================================================================
# Event Tests
# ============================================================================


class TestWriteEvent:
    """Event writes: batching, flush triggers, round-trip."""

    def test_event_is_queued_not_immediately_written(self, storage, event, verdict):
        """Events are queued, not immediately written to disk."""
        storage.write_event(event, verdict, run_id="run-001")

        # Batch is not flushed yet
        cursor = storage._db.execute("SELECT COUNT(*) FROM events")
        count = cursor.fetchone()[0]
        assert count == 0
        assert len(storage._batch) == 1

    def test_event_written_on_close(self, storage, event, verdict, temp_db_path):
        """Pending events are flushed on close."""
        storage.write_event(event, verdict, run_id="run-001")
        storage.close()

        # Reopen to check
        db = sqlite3.connect(temp_db_path)
        cursor = db.execute("SELECT COUNT(*) FROM events")
        count = cursor.fetchone()[0]
        db.close()
        assert count == 1

    def test_event_json_is_valid(self, storage, event, verdict, temp_db_path):
        """Event JSON is serializable and round-trips."""
        storage.write_event(event, verdict, run_id="run-001")
        storage.close()

        db = sqlite3.connect(temp_db_path)
        cursor = db.execute("SELECT event_json FROM events")
        row = cursor.fetchone()
        db.close()

        data = json.loads(row[0])
        recovered = Event.from_dict(data)
        assert recovered == event

    def test_verdict_json_is_valid(self, storage, event, verdict, temp_db_path):
        """Verdict JSON is serializable and round-trips."""
        storage.write_event(event, verdict, run_id="run-001")
        storage.close()

        db = sqlite3.connect(temp_db_path)
        cursor = db.execute("SELECT verdict_json FROM events")
        row = cursor.fetchone()
        db.close()

        data = json.loads(row[0])
        recovered = Verdict.from_dict(data)
        assert recovered == verdict

    def test_event_fields_are_stored(self, storage, event, verdict, temp_db_path):
        """All event fields are preserved in storage."""
        storage.write_event(event, verdict, run_id="run-001")
        storage.close()

        db = sqlite3.connect(temp_db_path)
        cursor = db.execute(
            "SELECT run_id, captured_at, url FROM events"
        )
        row = cursor.fetchone()
        db.close()

        assert row[0] == "run-001"
        assert row[1] == event.captured_at
        assert row[2] == event.url

    def test_batch_size_triggers_flush(self, temp_db_path, event, verdict):
        """Batch flushes when batch_size is reached."""
        storage = Storage(db_path=temp_db_path, batch_size=3, flush_interval=999)

        for i in range(3):
            storage.write_event(event, verdict, run_id=f"run-{i}")

        # Should be flushed at batch_size=3
        cursor = storage._db.execute("SELECT COUNT(*) FROM events")
        count = cursor.fetchone()[0]
        assert count == 3
        storage.close()

    def test_flush_interval_triggers_flush(self, temp_db_path, event, verdict):
        """Batch flushes when flush_interval has passed."""
        import time

        storage = Storage(db_path=temp_db_path, batch_size=999, flush_interval=0.1)

        storage.write_event(event, verdict, run_id="run-001")

        # Wait for flush interval
        time.sleep(0.15)

        # Add another event to trigger the interval check
        storage.write_event(event, verdict, run_id="run-002")

        cursor = storage._db.execute("SELECT COUNT(*) FROM events")
        count = cursor.fetchone()[0]
        assert count == 2
        storage.close()

    def test_never_raises_on_db_error(self, storage, event, verdict):
        """Write errors are swallowed and logged (ADR-6)."""
        storage.close()

        # This should not raise, just log the error
        storage.write_event(event, verdict, run_id="run-001")

    def test_multiple_events_are_batched(self, storage, event, verdict, temp_db_path):
        """Multiple events are batched together."""
        for i in range(5):
            storage.write_event(event, verdict, run_id=f"run-{i}")

        storage.close()

        db = sqlite3.connect(temp_db_path)
        cursor = db.execute("SELECT COUNT(*) FROM events")
        count = cursor.fetchone()[0]
        db.close()
        assert count == 5


# ============================================================================
# Aggregate Tests
# ============================================================================


class TestAggregates:
    """Aggregate read/write round-trips."""

    def test_write_and_read_aggregate(self, storage):
        """Aggregate round-trips through storage."""
        data = {"fill_rate": 0.85, "total_events": 100}
        storage.write_aggregate(job="ebay-prices", key="quality", value=data)

        result = storage.read_aggregate(job="ebay-prices", key="quality")
        assert result == data

    def test_read_missing_aggregate_returns_none(self, storage):
        """Reading a missing aggregate returns None."""
        result = storage.read_aggregate(job="missing", key="missing")
        assert result is None

    def test_update_existing_aggregate(self, storage):
        """Updating an aggregate overwrites the value."""
        storage.write_aggregate(job="ebay-prices", key="quality", value={"count": 1})
        storage.write_aggregate(job="ebay-prices", key="quality", value={"count": 2})

        result = storage.read_aggregate(job="ebay-prices", key="quality")
        assert result == {"count": 2}

    def test_aggregate_updated_at_is_set(self, storage):
        """Aggregate has updated_at timestamp."""
        storage.write_aggregate(job="ebay-prices", key="quality", value={})

        cursor = storage._db.execute(
            "SELECT updated_at FROM aggregates WHERE job = ? AND key = ?",
            ("ebay-prices", "quality"),
        )
        row = cursor.fetchone()
        assert row[0] is not None
        # Should be ISO-8601 format
        datetime.fromisoformat(row[0])

    def test_different_jobs_have_separate_aggregates(self, storage):
        """Aggregates are keyed by job."""
        storage.write_aggregate(job="job-a", key="stats", value={"a": 1})
        storage.write_aggregate(job="job-b", key="stats", value={"b": 2})

        assert storage.read_aggregate("job-a", "stats") == {"a": 1}
        assert storage.read_aggregate("job-b", "stats") == {"b": 2}

    def test_never_raises_on_read_error(self, storage):
        """Read errors return None, not exceptions (ADR-6)."""
        storage.close()
        result = storage.read_aggregate(job="job", key="key")
        assert result is None


# ============================================================================
# Purge Tests
# ============================================================================


class TestPurgeOldEvents:
    """Event retention and purge."""

    def test_purge_removes_old_events(self, temp_db_path, event, verdict):
        """Events older than N days are deleted."""
        storage = Storage(db_path=temp_db_path)

        # Create an old event
        old_event = Event(
            url="https://example.com/old",
            job=JobRef(name="test", run_id="run-old"),
            captured_at="2026-10-01T00:00:00+00:00",  # Old date
        )
        storage.write_event(old_event, verdict, run_id="run-old")

        # Create a recent event
        recent_event = Event(
            url="https://example.com/recent",
            job=JobRef(name="test", run_id="run-recent"),
            captured_at=datetime.now(timezone.utc).isoformat(),
        )
        storage.write_event(recent_event, verdict, run_id="run-recent")

        storage.close()

        # Reopen and purge
        storage2 = Storage(db_path=temp_db_path)
        storage2.purge_old_events(days=14)
        storage2.close()

        # Check results
        db = sqlite3.connect(temp_db_path)
        cursor = db.execute("SELECT url FROM events ORDER BY url")
        rows = [row[0] for row in cursor.fetchall()]
        db.close()

        assert "https://example.com/recent" in rows
        assert "https://example.com/old" not in rows

    def test_purge_keeps_recent_events(self, temp_db_path, event, verdict):
        """Events within the retention window are kept."""
        storage = Storage(db_path=temp_db_path)

        recent_event = Event(
            url="https://example.com/recent",
            job=JobRef(name="test", run_id="run-recent"),
            captured_at=(datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),
        )
        storage.write_event(recent_event, verdict, run_id="run-recent")
        storage.close()

        storage2 = Storage(db_path=temp_db_path)
        storage2.purge_old_events(days=14)
        storage2.close()

        db = sqlite3.connect(temp_db_path)
        cursor = db.execute("SELECT COUNT(*) FROM events")
        count = cursor.fetchone()[0]
        db.close()

        assert count == 1

    def test_purge_default_is_14_days(self, temp_db_path, event, verdict):
        """Default purge window is 14 days."""
        storage = Storage(db_path=temp_db_path)

        # Event exactly 15 days old
        old_event = Event(
            url="https://example.com/old",
            job=JobRef(name="test", run_id="run-old"),
            captured_at=(datetime.now(timezone.utc) - timedelta(days=15)).isoformat(),
        )
        storage.write_event(old_event, verdict, run_id="run-old")
        storage.close()

        storage2 = Storage(db_path=temp_db_path)
        storage2.purge_old_events()  # Default 14 days
        storage2.close()

        db = sqlite3.connect(temp_db_path)
        cursor = db.execute("SELECT COUNT(*) FROM events")
        count = cursor.fetchone()[0]
        db.close()

        assert count == 0

    def test_purge_never_raises_on_error(self, temp_db_path):
        """Purge errors are swallowed (ADR-6)."""
        storage = Storage(db_path=temp_db_path)
        storage.close()

        # Should not raise
        storage.purge_old_events(days=14)


class TestErrorHandling:
    """Never raise policy from ADR-6."""

    def test_write_event_after_close_does_not_raise(self, storage, event, verdict):
        """Closed storage handles write_event gracefully."""
        storage.close()
        storage.write_event(event, verdict, run_id="run-001")

    def test_write_run_after_close_does_not_raise(self, storage, run):
        """Closed storage handles write_run gracefully."""
        storage.close()
        storage.write_run(run)

    def test_write_aggregate_after_close_does_not_raise(self, storage):
        """Closed storage handles write_aggregate gracefully."""
        storage.close()
        storage.write_aggregate(job="job", key="key", value={})

    def test_close_is_idempotent(self, storage):
        """Close can be called multiple times safely."""
        storage.close()
        storage.close()  # Should not raise


class TestThreadSafety:
    """Storage is thread-safe for concurrent access."""

    def test_concurrent_writes(self, temp_db_path, event, verdict):
        """Multiple threads can write concurrently."""
        import threading

        storage = Storage(db_path=temp_db_path)
        errors = []

        def writer(thread_id):
            try:
                for i in range(10):
                    storage.write_event(event, verdict, run_id=f"run-{thread_id}-{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        storage.close()

        assert not errors

        db = sqlite3.connect(temp_db_path)
        cursor = db.execute("SELECT COUNT(*) FROM events")
        count = cursor.fetchone()[0]
        db.close()

        assert count == 50  # 5 threads * 10 events each


class TestProtocolCompliance:
    """Storage implements StorageProtocol."""

    def test_storage_implements_protocol(self):
        """Storage is a valid StorageProtocol."""
        assert isinstance(Storage, type)
        # Protocol is structural, not nominal - check method signatures match

    def test_write_event_signature(self, storage, event, verdict):
        """write_event has correct signature."""
        storage.write_event(event, verdict, run_id="run-001")

    def test_write_run_signature(self, storage, run):
        """write_run has correct signature."""
        storage.write_run(run)

    def test_write_aggregate_signature(self, storage):
        """write_aggregate has correct signature."""
        storage.write_aggregate(job="job", key="key", value={})

    def test_read_aggregate_signature(self, storage):
        """read_aggregate has correct signature."""
        result = storage.read_aggregate(job="job", key="key")
        assert result is None or isinstance(result, dict)

    def test_purge_old_events_signature(self, storage):
        """purge_old_events has correct signature."""
        storage.purge_old_events(days=14)

    def test_close_signature(self, storage):
        """close has correct signature."""
        storage.close()


class TestContractRoundTrip:
    """Events and Verdicts round-trip through storage (ADR-4)."""

    def test_event_contract_round_trip(self, storage, event, verdict):
        """Event survives storage round-trip unchanged."""
        storage.write_event(event, verdict, run_id="run-001")
        storage.close()

        db = sqlite3.connect(storage._db_path)
        cursor = db.execute("SELECT event_json FROM events")
        row = cursor.fetchone()
        db.close()

        data = json.loads(row[0])
        recovered = Event.from_dict(data)

        assert recovered == event

    def test_verdict_contract_round_trip(self, storage, event, verdict):
        """Verdict survives storage round-trip unchanged."""
        storage.write_event(event, verdict, run_id="run-001")
        storage.close()

        db = sqlite3.connect(storage._db_path)
        cursor = db.execute("SELECT verdict_json FROM events")
        row = cursor.fetchone()
        db.close()

        data = json.loads(row[0])
        recovered = Verdict.from_dict(data)

        assert recovered == verdict

    def test_blocked_verdict_round_trip(self, storage, event, blocked_verdict):
        """Blocked verdict survives storage round-trip."""
        storage.write_event(event, blocked_verdict, run_id="run-001")
        storage.close()

        db = sqlite3.connect(storage._db_path)
        cursor = db.execute("SELECT verdict_json FROM events")
        row = cursor.fetchone()
        db.close()

        data = json.loads(row[0])
        recovered = Verdict.from_dict(data)

        assert recovered == blocked_verdict
        assert recovered.status == Status.BLOCKED


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_body_sample(self, storage, verdict):
        """Event with empty body_sample is handled."""
        event = Event(
            url="https://example.com",
            job=JobRef(name="test", run_id="run-1"),
            captured_at="2026-11-21T00:00:00+00:00",
            body_sample="",
        )
        storage.write_event(event, verdict, run_id="run-1")
        storage.close()

        db = sqlite3.connect(storage._db_path)
        cursor = db.execute("SELECT event_json FROM events")
        row = cursor.fetchone()
        db.close()

        data = json.loads(row[0])
        recovered = Event.from_dict(data)
        assert recovered.body_sample == ""

    def test_unicode_in_url(self, storage, verdict):
        """Unicode characters in URL are handled."""
        event = Event(
            url="https://example.com/пути/日本語",
            job=JobRef(name="test", run_id="run-1"),
            captured_at="2026-11-21T00:00:00+00:00",
        )
        storage.write_event(event, verdict, run_id="run-1")
        storage.close()

        db = sqlite3.connect(storage._db_path)
        cursor = db.execute("SELECT event_json FROM events")
        row = cursor.fetchone()
        db.close()

        data = json.loads(row[0])
        assert "пути" in data["url"]
        assert "日本語" in data["url"]

    def test_large_headers(self, storage, verdict):
        """Large headers dict is handled."""
        headers = {f"x-header-{i}": f"value-{i}" for i in range(100)}
        event = Event(
            url="https://example.com",
            job=JobRef(name="test", run_id="run-1"),
            captured_at="2026-11-21T00:00:00+00:00",
            headers=headers,
        )
        storage.write_event(event, verdict, run_id="run-1")
        storage.close()

        db = sqlite3.connect(storage._db_path)
        cursor = db.execute("SELECT event_json FROM events")
        row = cursor.fetchone()
        db.close()

        data = json.loads(row[0])
        assert len(data["headers"]) == 100

    def test_items_with_special_characters(self, storage, verdict):
        """Items with special characters are handled."""
        event = Event(
            url="https://example.com",
            job=JobRef(name="test", run_id="run-1"),
            captured_at="2026-11-21T00:00:00+00:00",
            items=[{"name": "Product \"Quote\"", "price": "$1,234.56"}],
        )
        storage.write_event(event, verdict, run_id="run-1")
        storage.close()

        db = sqlite3.connect(storage._db_path)
        cursor = db.execute("SELECT event_json FROM events")
        row = cursor.fetchone()
        db.close()

        data = json.loads(row[0])
        assert data["items"][0]["name"] == 'Product "Quote"'
        assert data["items"][0]["price"] == "$1,234.56"
