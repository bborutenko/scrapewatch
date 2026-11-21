"""SQLite persistence: connection, schema, CRUD operations.

Thread-safe storage layer. Analyzer thread writes events, runs, aggregates.
Never raises into caller code — errors are caught and logged (ADR-6).
"""

import json
import sqlite3
import time
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Protocol

from ..config import get_logger, get_settings
from ..core.event import Event
from ..core.verdict import Verdict
from .models import Run

logger = get_logger()

__all__ = ["StorageProtocol", "Storage"]


class StorageProtocol(Protocol):
    """Interface for scrapewatch storage backends."""

    def write_event(self, event: Event, verdict: Verdict, run_id: str) -> None:
        """Write an event and its verdict. Never raises."""
        ...

    def write_run(self, run: Run) -> None:
        """Write or update a run record. Never raises."""
        ...

    def write_aggregate(self, job: str, key: str, value: dict) -> None:
        """Write or update an aggregate. Never raises."""
        ...

    def read_aggregate(self, job: str, key: str) -> dict | None:
        """Read an aggregate value, or None if not found."""
        ...

    def purge_old_events(self, days: int = 14) -> None:
        """Delete events older than N days. Never raises."""
        ...

    def close(self) -> None:
        """Flush pending writes and close connection."""
        ...


class Storage:
    """SQLite-backed storage for events, runs, and aggregates.

    Uses WAL mode for concurrent read/write. Writes are batched for performance.
    All methods are safe to call from analyzer thread.

    Usage:
        storage = Storage()
        storage.write_event(event, verdict, run_id="...")
        storage.write_run(run)
        storage.close()
    """

    def __init__(
        self,
        db_path: str | None = None,
        batch_size: int | None = None,
        flush_interval: float | None = None,
    ) -> None:
        settings = get_settings()
        self._db_path = db_path if db_path is not None else settings.storage.db_path
        self._batch_size = batch_size if batch_size is not None else settings.storage.batch_size
        self._flush_interval = flush_interval if flush_interval is not None else settings.storage.flush_interval
        self._batch: list[tuple[str, str, str, str, str]] = []
        self._last_flush = time.time()

        self._db = sqlite3.connect(self._db_path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        """Create tables if they don't exist."""
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                job TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                events INTEGER DEFAULT 0,
                analyzer_errors INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                url TEXT NOT NULL,
                event_json TEXT NOT NULL,
                verdict_json TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(id)
            );

            CREATE TABLE IF NOT EXISTS aggregates (
                job TEXT NOT NULL,
                key TEXT NOT NULL,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (job, key)
            );

            CREATE INDEX IF NOT EXISTS idx_events_run_id ON events(run_id);
            CREATE INDEX IF NOT EXISTS idx_events_captured_at ON events(captured_at);
            """
        )
        self._db.commit()

    def write_event(self, event: Event, verdict: Verdict, run_id: str) -> None:
        """Queue an event for batched write.

        Flushes when batch is full or flush_interval has passed.
        Never raises — errors are silently ignored (ADR-6).
        """
        try:
            self._batch.append(
                (
                    run_id,
                    event.captured_at,
                    event.url,
                    json.dumps(event.to_dict(), separators=(",", ":")),
                    json.dumps(verdict.to_dict(), separators=(",", ":")),
                )
            )

            now = time.time()
            if len(self._batch) >= self._batch_size or now - self._last_flush > self._flush_interval:
                self._flush()
        except Exception as e:
            logger.error(f"write_event failed: {e!r}")

    def _flush(self) -> None:
        """Write batched events to database."""
        if not self._batch:
            return

        try:
            self._db.executemany(
                """
                INSERT INTO events (run_id, captured_at, url, event_json, verdict_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                self._batch,
            )
            self._db.commit()
            self._batch.clear()
            self._last_flush = time.time()
        except Exception as e:
            logger.error(f"flush failed: {e!r}")

    def write_run(self, run: Run) -> None:
        """Insert or update a run record."""
        try:
            self._db.execute(
                """
                INSERT INTO runs (id, job, started_at, ended_at, events, analyzer_errors)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    ended_at = excluded.ended_at,
                    events = excluded.events,
                    analyzer_errors = excluded.analyzer_errors
                """,
                (run.id, run.job, run.started_at, run.ended_at, run.events, run.analyzer_errors),
            )
            self._db.commit()
        except Exception as e:
            logger.error(f"write_run failed: {e!r}")

    def write_aggregate(self, job: str, key: str, value: dict) -> None:
        """Insert or update an aggregate."""
        try:
            now = datetime.now(timezone.utc).isoformat()
            self._db.execute(
                """
                INSERT INTO aggregates (job, key, value_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(job, key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (job, key, json.dumps(value, separators=(",", ":")), now),
            )
            self._db.commit()
        except Exception as e:
            logger.error(f"write_aggregate failed: {e!r}")

    def read_aggregate(self, job: str, key: str) -> dict | None:
        """Read an aggregate value, or None if not found."""
        try:
            cursor = self._db.execute(
                "SELECT value_json FROM aggregates WHERE job = ? AND key = ?",
                (job, key),
            )
            row = cursor.fetchone()
            return json.loads(row[0]) if row else None
        except Exception:
            return None

    def purge_old_events(self, days: int = 14) -> None:
        """Delete events older than N days."""
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            self._db.execute(
                "DELETE FROM events WHERE captured_at < ?",
                (cutoff.isoformat(),),
            )
            self._db.commit()
        except Exception as e:
            logger.error(f"purge_old_events failed: {e!r}")

    def close(self) -> None:
        """Flush pending writes and close connection."""
        self._flush()
        self._db.close()

    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Context manager for explicit transaction control."""
        try:
            yield self._db
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise
