"""Storage layer: SQLite persistence for events, runs, and aggregates."""

from .models import Aggregate, Run
from .sqlite import Storage, StorageProtocol

__all__ = ["Storage", "StorageProtocol", "Run", "Aggregate"]
