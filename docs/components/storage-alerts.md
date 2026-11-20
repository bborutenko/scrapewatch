# Storage & Alerts — Persistence, Notification, CLI

**Document type:** Component design — target state
**Status:** (planned) Phase 4 — no implementation exists yet
**Depends on:** [ADR-6](../contracts/decisions.md) (failure policy), [data-quality.md](./data-quality.md) (persistes its aggregates), [contracts/interfaces.md Part A](../contracts/interfaces.md) (stored shapes)

## 1. Role

Storage turns the stream of Verdicts and job aggregates into an answerable history: *when was this job last healthy, what broke, did we lose events?* Alerts turn interesting state transitions into notifications. The CLI exposes both to humans without a database browser. In v0.1 all three run in-process, on SQLite, with zero configuration.

## 2. Planned layout

| Path | Responsibility |
|---|---|
| `scrapewatch/storage/sqlite.py` | connection management, schema, retention |
| `scrapewatch/storage/alerts.py` | alert sinks: logger, webhook, Telegram |
| `scrapewatch/cli.py` | `scrapewatch check`, `scrapewatch report` |

## 3. SQLite schema (planned)

Three tables, one file (default `./scrapewatch.db`, configurable via `watch(..., db=...)`):

```sql
runs     (id TEXT PK, job TEXT, started_at TEXT, ended_at TEXT, events INTEGER, analyzer_errors INTEGER)
events   (id INTEGER PK, run_id TEXT, captured_at TEXT, url TEXT, event_json TEXT, verdict_json TEXT)
aggregates (job TEXT, key TEXT, value_json TEXT, updated_at TEXT, PRIMARY KEY (job, key))
```

Design notes:

- `event_json` / `verdict_json` store the contract shapes verbatim ([ADR-4](../contracts/decisions.md)) — the database is queryable by the same schema every future SDK speaks; no relational translation layer to drift.
- Self-diagnostic counter lives on `runs` ([ADR-6](../contracts/decisions.md)): `analyzer_errors` is first-class data, surfaced by `report`.
- Writes happen on the analyzer thread only; batched (default every 50 events or 10 s, whichever first). A failed write degrades to in-memory operation and increments `analyzer_errors` — it never stops analysis.
- Retention: default 14 days of `events` rows; `aggregates` and `runs` kept indefinitely (tiny). Configurable; purge runs opportunistically after batch writes.

## 4. Alert channels

Alerts fire on job state transitions (`ok → blocked/garbage/drifted` and recovery back to `ok`), not on every bad event — per-event alerting would be spam and get muted (same reasoning as drift thresholds in [data-quality.md §5](./data-quality.md)).

| Sink | Configuration | Delivery |
|---|---|---|
| `sw.LogAlert()` | none (default) | WARNING-level log lines |
| `sw.WebhookAlert(url)` | URL | JSON POST: job, transition, verdict, evidence; 5 s timeout, fire-and-forget |
| `sw.TelegramAlert()` | `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` env vars | short human message |

All sinks share the never-raise wrapper: a dead webhook must not take the analyzer down (it increments `analyzer_errors` instead). Telegram uses stdlib `urllib` in v0.1 — no dependency added for a notification sink.

Debounce: identical transitions for the same job alert at most once per 15 minutes (configurable); the recovery alert always sends immediately.

## 5. CLI

### `scrapewatch check <file-or-url> [--status N]`

One-shot classification: load HTML from a file or URL, build an Event, run the engine synchronously, print the Verdict as a table (status, detector, reason, confidence, matched signatures). Doubles as the fixture-authoring tool — the loop for writing a new detector is: save page → `scrapewatch check page.html` → adjust YAML → repeat, no Python needed.

### `scrapewatch report [--job NAME] [--db PATH]`

Terminal health summary from SQLite:

```text
job ebay-prices          state: drifted (since 2026-11-13 14:02)
  data freshness   last good items:  3 h 12 m ago
  page freshness   last ok response: 4 m ago
  fill rate        price: 61% ▼▼   title: 100%
  drift            field_emptiness fired 13:58 (price < 80%)
  self-diag        analyzer_errors: 0
```

The two freshness numbers side by side are the product's headline answer ([data-quality.md §6](./data-quality.md)): real pages + stale data = broken extraction; stale both = blocked pipeline.

## 6. Testing strategy

- Storage round-trip: write N events → read back → validate against the contract JSON Schema (this is the CI check mandated by [ADR-4](../contracts/decisions.md)).
- Alert sinks against a local HTTP server: assert payload shape, debounce window, and that a connection-refused sink leaves the analyzer alive (fault injection per [ADR-6](../contracts/decisions.md)).
- CLI: golden-output tests for `report` against a seeded database.

## 7. Open questions (Phase 4)

- WAL mode for SQLite (concurrent read during write)? Default yes if no surprises on Windows.
- Retention enforcement interval — piggyback on batch writes (current answer) vs scheduled?
- Should `report` grow a `--json` flag from day one for scriptability? (Lean yes — costs nothing.)
