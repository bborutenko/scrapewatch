# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2024-XX-XX

### Added

#### Core Engine
- Event/Verdict data contract (interfaces.md Part A)
- YAML-based detector rules engine
- `Engine.observe(event) -> Verdict` — pure classification function
- Built-in `cloudflare-challenge` detector

#### Interceptors
- **requests**: `WatchedSession` — subclass of `requests.Session`
- **httpx**: `WatchedClient` (sync) and `WatchedAsyncClient` (async)
- **Playwright**: `WatchedSyncBrowser`, `WatchedAsyncBrowser`, 
  `WatchedSyncBrowserContext`, `WatchedAsyncBrowserContext`

#### Protocols (Public API)
- `sw.watch(client, job, rules)` — passive observation
- `sw.guarded(client, job, rules)` — verdict-as-exception (stub, Phase 2)
- `sw.fetch(fn, *args, job, **kwargs)` — reactive context (stub, Phase 2)

#### Infrastructure
- `AsyncAnalyzer` — background thread with bounded queue
- `SyncAnalyzer` — inline processing for reactive modes
- Configuration system (`sw.configure()`)
- Logging with `scrapewatch` prefix

#### Tests
- 149 tests total
- Unit tests for all interceptors
- Integration tests with real HTTP requests
- Live tests for Playwright with real browsers

### Changed

- Moved client types from `client.py` to `interceptors/client.py`
- Removed global `_default_analyzer` state
- Made `analyzer` and `engine` explicit parameters (no `None`)

### Technical Details

- Python 3.10+ support
- Optional extras: `requests`, `httpx`, `playwright`, `all`
- Zero business logic in interceptors (ADR-2)
- Fire-and-forget guarantee (ADR-6)

---

## Future Roadmap

### Phase 2 (Planned)
- Reactive modes: `guarded()` and `fetch()` implementations
- More built-in detectors (DataDome, Akamai, Kasada, etc.)

### Phase 3 (Planned)
- Item schema validation
- Fill rate tracking
- Drift detection (volume, structure hash)

### Phase 4 (Planned)
- SQLite storage
- Alert channels (webhook, Telegram)
- CLI: `scrapewatch check`, `scrapewatch report`
