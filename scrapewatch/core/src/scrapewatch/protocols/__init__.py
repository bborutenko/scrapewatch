"""Protocols — public API for watching and reacting to scraper traffic.

This package contains the user-facing functions:
- watch(): Passive observation (async verdicts, no code change)
- guarded(): Verdict-as-exception wrapper (Phase 2)
- fetch(): Reactive context manager with synchronous verdict (Phase 2)

Each protocol creates the appropriate analyzer/engine and wraps clients.
"""

from .fetch import fetch
from .guarded import guarded
from .watch import watch

__all__ = ["watch", "guarded", "fetch"]
