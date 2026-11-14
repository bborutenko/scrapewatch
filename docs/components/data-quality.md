# Data Quality — Schemas, Drift, Freshness

**Document type:** Component design — target state
**Status:** (planned) Phase 3 — no implementation exists yet
**Depends on:** [contracts/interfaces.md Part B.4](../contracts/interfaces.md) (schema declaration format), [core-engine.md](./core-engine.md) (item validation hooks into the engine)

## 1. Role

Fake-page detectors judge *responses*; data quality judges *data*. This subsystem owns everything that turns per-item checks into job-level signals: fill rate, drift rules, freshness. It is the part of Scrapewatch that catches the failure mode where every response renders fine but the site was redesigned and selectors silently return `None` — and it produces the `drifted` verdict status defined in [CONCEPTS.md](../CONCEPTS.md).

Split of responsibility (keep it crisp):

| Question | Owner |
|---|---|
| Is this response a real page? | core engine detectors (`blocked` / `garbage`) |
| Do these items conform to the schema? | **data quality** — per-item validation, `garbage` on hard violations |
| Is the job's data shape changing over time? | **data quality** — aggregates, `drifted` |
| When was data last real? | **data quality** — freshness |

## 2. Planned layout

| Path | Responsibility |
|---|---|
| `scrapewatch/storage/quality.py` | rolling aggregates (in-memory windows per job, persisted periodically) |
| `scrapewatch/storage/quality_rules.py` | drift rule evaluation against aggregates |
| (engine hook) | per-item schema validation called from `engine.observe()` when `event.items` is present |

Stateful by design (unlike the pure core), so it lives next to storage — the aggregates *are* the state. Per [ADR-6](../contracts/decisions.md), all of it runs on the analyzer thread and can never raise into user code.

## 3. Per-item validation

- Registered per job via `sw.watch(client, job=..., schema=sw.Schema({...}))` or `sw.job(..., schema=...)`.
- Checks in v0.1: `type`, `required`, `range`, `min_length`/`max_length`, `enum` (format: [interfaces.md B.4](../contracts/interfaces.md)).
- Each item scores individually; the event's item verdict is attached to the overall Verdict:
  - all items pass → no effect (`ok` stays `ok`);
  - some items fail → verdict `garbage`, `detector_id="schema"`, evidence lists offending fields and counts;
  - items present but schema not registered → skipped, one-time INFO log.

## 4. Rolling aggregates (per job, per field)

| Aggregate | Definition |
|---|---|
| `fill_rate[field]` | share of the last N items (default window 500) where the field is present, non-null and type-valid |
| `volume` | events per hour, compared against the trailing baseline (previous 24 h, minimum 50 events) |
| `structure_hash` | SHA-256 of the normalized DOM tag sequence (tags only, no attributes/text) of the page that produced the items |
| `freshness` | age of the last `ok` verdict and of the last schema-passing item batch |

Aggregates update on the analyzer thread after each event; snapshots persist to SQLite on a period (default every 100 events) so a process restart does not lose the baseline.

## 5. Drift rules

| Rule | Fires when | Default threshold | Rationale |
|---|---|---|---|
| `volume_drop` | current events/hour < baseline × (1 − threshold) | 50% | pipeline or crawl pattern broke |
| `field_emptiness` | `fill_rate[field]` < threshold for a required field | 80% (from ~100% baseline) | selector broke — the classic silent death |
| `structure_change` | `structure_hash` differs from baseline hash for > threshold of recent events | 70% of window | site redesigned |

When a rule fires, the job enters state `drifted`, a Verdict(status=`drifted`, detector_id=rule name) is recorded, and alerts dispatch. Recovery: rule condition false for one full window → job returns to `ok` (state transitions are themselves Events in storage, so reports show incident intervals).

Thresholds are configurable per job (`sw.watch(..., drift={"field_emptiness": 0.9})`). Defaults are deliberately conservative: a drift alert must mean something, or users mute the channel.

## 6. Freshness

Two numbers per job, shown by `scrapewatch report`:

- **data freshness** — time since items last passed schema validation;
- **page freshness** — time since the last `ok` response verdict.

A job can have perfect page freshness and stale data freshness (real pages, broken extraction) — the gap between the two numbers is itself the diagnosis.

## 7. Testing strategy

- Fixture replay pairs under `tests/fixtures/quality/`: `before.html` / `after.html` with identical item schemas — `after` (redesigned) must flip `structure_hash` and trip `field_emptiness`.
- Synthetic item streams (property-based: random valid items → no drift; injected 30% nulls in one field → `field_emptiness` fires within one window).
- Window math unit tests: exactly-at-threshold and just-below-threshold cases.

## 8. Open questions (Phase 3)

- Window semantics for low-volume jobs (< 50 events/day): hours-based windows instead of count-based?
- Should `structure_hash` use the raw page or only the region that produced items (more precise, needs selector context from the user)?
- Multi-schema jobs (different item types in one job) — needed by anyone? Default: one schema per job until someone asks.
