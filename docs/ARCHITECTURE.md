# Architecture — Scrapewatch

**Document type:** Architecture — cross-cutting design
**Status:** Target state, approved 2026-11-13 — no implementation exists yet
**Applies to:** scrapewatch v0.1 (Python library only; see [roadmap.md](./roadmap.md))

## 1. Overview and positioning

Scrapewatch is an observability layer for web scraping. It answers one question — *is the data this pipeline collects still real?* — by classifying every response (fake-200 detection), validating every extracted record (schema), and watching job-level aggregates (drift, freshness). Vocabulary: [CONCEPTS.md](./CONCEPTS.md).

Positioning constraints that shape everything below:

| Scrapewatch is | Scrapewatch is not |
|---|---|
| A wrapper over the user's existing transport | A scraping framework — it never issues its own crawl logic |
| A diagnostic that recognizes blocked/garbage responses | An anti-bot bypass — it does not defeat protections, it reports them |
| A library the user installs next to their scraper | A proxy pool, a headless-browser farm, or a data marketplace |

These constraints are strategic: they make Scrapewatch complementary to every scraping stack (requests, httpx, Scrapy, Playwright, Firecrawl, Crawl4AI, browser agents) rather than a competitor to any of them.

## 2. Package shape (planned)

```text
scrapewatch/               ← repository root
├── scrapewatch/           ← the Python package
│   ├── core/              ← pure engine: event.py, verdict.py, engine.py, rules.py
│   ├── interceptors/      ← requests.py, httpx.py, playwright.py
│   ├── storage/           ← sqlite.py, alerts.py
│   └── cli.py             ← `scrapewatch check` / `scrapewatch report`
├── rules/                 ← canonical YAML detector rules (packaged with the wheel)
├── tests/
│   ├── fixtures/          ← saved challenge-page snapshots, per detector id
│   └── ...
├── docs/                  ← this documentation
├── examples/              ← runnable examples: requests, httpx, Playwright, Scrapy
└── pyproject.toml
```

| Part | Path | Purity | Depends on |
|---|---|---|---|
| Core engine | `scrapewatch/core/` | pure — no I/O, no threads, no framework imports | nothing (stdlib only) |
| Interceptors | `scrapewatch/interceptors/` | impure by definition (wraps user transports) | `core` |
| Storage & alerts | `scrapewatch/storage/` | impure (SQLite, network for webhooks) | `core` |
| Rules | `rules/*.yaml` | data, not code | interpreted by `core` |

## 3. The core boundary

The single most important architectural rule (see [ADR-2](./contracts/decisions.md)):

> **`scrapewatch/core` is a pure library. Its entire surface is one entry point: `engine.observe(event: Event) -> Verdict`. No network, no disk, no threads, no framework imports.**

Everything else — interceptors, storage, alerting, CLI, and any future HTTP server — is a shell around this function. The consequences:

- The engine is unit-testable in one line: build an `Event`, call `observe`, assert the `Verdict`. Snapshot tests over `tests/fixtures/` (see [components/core-engine.md](./components/core-engine.md)).
- The future polyglot split (§8) becomes a mechanical port of one module, not a rewrite.
- Business logic physically cannot leak into HTTP handlers or Playwright callbacks, because the core has nowhere to leak it to.

The `Event`/`Verdict` structures themselves are the contract — field-by-field definition in [contracts/interfaces.md Part A](./contracts/interfaces.md).

## 4. End-to-end data flow

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                            USER SCRAPER                                 │
│          (requests / httpx / Playwright / Scrapy / agent)               │
└───────────────┬─────────────────────────────────────────────────────────┘
                │ response objects pass through unchanged
                ▼
┌──────────────────────────┐   Event (dataclass)    ┌───────────────────┐
│  INTERCEPTORS            │ ──────────────────────▶ │  BACKGROUND       │
│  sw.watch(client)        │   bounded queue,        │  ANALYZER         │
│  captures: url, status,  │   fire-and-forget       │  (worker thread)  │
│  headers, body sample+   │                         │                   │
│  hash, latency, job ctx  │ ◀─── never blocks,      │  engine.observe() │
└──────────────────────────┘      never raises       │  ↓                │
                                                      │  Verdict          │
                                          ┌───────────┴───────────┐
                                          ▼                       ▼
                                  ┌──────────────┐      ┌────────────────┐
                                  │ STORAGE      │      │ DATA QUALITY   │
                                  │ SQLite       │      │ fill rate,     │
                                  │ (runs/events)│      │ drift rules,   │
                                  └──────┬───────┘      │ freshness      │
                                         │              └───────┬────────┘
                                         ▼                      ▼
                                  ┌────────────────────────────────────┐
                                  │ ALERTS: log / webhook / Telegram   │
                                  └────────────────────────────────────┘
```

The user-visible loop is deliberately tiny: wrap the client once; Scrapewatch does the rest out-of-band. The scraper's own code path never waits on Scrapewatch.

## 5. Integration levels

Scrapewatch attaches at the lowest common layers of the scraping ecosystem, not per-framework ([ADR-5](./contracts/decisions.md)):

| Level | Mechanism | What it covers | Status |
|---|---|---|---|
| L1 — HTTP clients | `sw.watch()` over `requests.Session`, `httpx.Client` / `httpx.AsyncClient` | ~all pure-Python scraping | (planned, Phase 2) |
| L2 — Browser engine | `sw.watch()` over a Playwright `Browser`/`BrowserContext`: response + navigation listeners | Playwright users, and browser agents built on Playwright | (planned, Phase 2) |
| L3 — Explicit API | `with sw.job(...) as j: j.observe(url, resp); j.items(rows)` | anything exotic or hand-rolled | (planned, Phase 2) |
| L4 — Framework adapters | Scrapy downloader middleware, Firecrawl client wrapper, Crawlee hooks | long tail | **(future)** |

Rationale: L1+L2+L3 already intercept nearly every Python scraper; framework adapters are thin plugins over the same core, added when users ask for them. Details: [components/interceptors.md](./components/interceptors.md).

## 6. Operating modes

| Mode | What runs where | Status |
|---|---|---|
| **In-process** | Engine + analyzer + SQLite + alerts inside the user's process. Zero infrastructure; `pip install scrapewatch` is the whole setup. | v0.1 (planned) |
| **Sidecar server** | Standalone Scrapewatch server receiving Events over HTTP (`POST /v1/events`); multi-scraper dashboards, team alerting, history. | **(future)** — out of scope for v0.1 ([ADR-1](./contracts/decisions.md)) |
| **Embedded foreign core** | The Python core re-implemented in Rust (PyO3 / napi-rs / WASM) or served by a Go binary; TS/Go SDKs appear. | **(future)** — see §8 |

The mode switch, when it exists, is a configuration change, not a code change: the same Events, the same contract.

## 7. Failure policy

Observability that can break the thing it observes is worse than no observability ([ADR-6](./contracts/decisions.md)). Concrete rules for the interceptor and analyzer:

1. **Never block.** Interception enqueues and returns immediately; analysis happens on a background worker. Budget per captured response: microseconds on the caller's thread.
2. **Never raise.** Any exception anywhere inside Scrapewatch is caught, counted in a self-diagnostic counter, and logged (level `WARNING` or lower). Not a single exception may propagate into user scraping code.
3. **Degrade, don't die.** The event queue is bounded (default 10,000 events). On overflow the oldest events are dropped and a `dropped_events` counter increments; on SQLite write failure the analyzer keeps running with results in memory only.
4. **Be honest about it.** `scrapewatch report` (planned, Phase 4) surfaces the self-diagnostic counters, so silent Scrapewatch failure is itself observable.

## 8. Core extraction paths (future)

v0.1 is Python-only, but the design keeps three extraction doors open without committing to any ([ADR-1](./contracts/decisions.md), [ADR-4](./contracts/decisions.md)):

| Path | Shape | What travels |
|---|---|---|
| Rust core | `core/` ported to Rust; Python and TS bindings via PyO3 / napi-rs; WASM build for the docs playground | The `Event → Verdict` function and the YAML rules |
| Go server | Go binary implementing `POST /v1/events`; SDKs in any language become thin HTTP clients | Same contract, over the wire |
| Status quo + WASM | Python core stays; rules engine compiled to WASM for a browser playground on the project site | Detectors only |

All three paths share the assets that v0.1 builds anyway: the Event/Verdict contract (JSON-Schema-validatable), the YAML rules as data, and the fixture corpus. That is the entire point of [ADR-2](./contracts/decisions.md) and [ADR-3](./contracts/decisions.md): the port cost is bounded by design, not by luck.

## 9. Where to go next

- The exact field-level contract: [contracts/interfaces.md](./contracts/interfaces.md)
- Why each structural choice was made: [contracts/decisions.md](./contracts/decisions.md)
- Build order and gates: [roadmap.md](./roadmap.md)
