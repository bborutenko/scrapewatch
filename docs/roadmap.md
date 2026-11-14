# Roadmap — Scrapewatch v0.1

**Document type:** Delivery plan
**Status:** Approved 2026-11-13 — implementation not started
**Estimates:** person-days (`ed`), assuming one developer working alone

Priority rule when time is short: Phases 1–2 are the product; Phases 3–4 are its price tag (what a subscription tier would eventually sell); Phase 0 is never skipped.

## 1. Phase 0 — Skeleton (1–2 ed)

**Scope:** package skeleton with the architecture's disciplines baked in from the first commit: `scrapewatch/core` (pure), `scrapewatch/interceptors`, `scrapewatch/storage` stubs, `rules/` directory with the rule loader interface, `tests/` with fixtures directory, `pyproject.toml` (Apache-2.0, Python ≥3.10), ruff + pytest wired, GitHub Actions CI (lint + tests matrix).

**Done when:** `from scrapewatch.core import engine` imports; `Event`/`Verdict` dataclasses exist per [contracts/interfaces.md Part A](./contracts/interfaces.md); CI green on an empty test suite.

## 2. Phase 1 — Fake-page detectors (~1 week, 4–6 ed)

**Scope:** the rule engine and the first 8–10 detectors as YAML rules: `cloudflare-challenge`, `datadome`, `akamai`, `kasada`, `captcha-wall` (generic), `empty-spa-shell`, `login-wall`, `geo-block`, `soft-404`. Detector evaluation order: cheap matchers (headers, title) before body regexes. Fixture corpus: saved snapshots of real challenge pages under `tests/fixtures/<detector-id>/*.html`.

**Done when:** `engine.observe(event)` returns the correct verdict on every fixture; a challenge page behind HTTP 200 is classified `blocked`, not `ok`. See [components/core-engine.md](./components/core-engine.md).

## 3. Phase 2 — Interceptors (3–4 ed)

**Scope:** `sw.watch()` for `requests.Session`, `httpx.Client`, `httpx.AsyncClient`, Playwright `Browser`/`BrowserContext`; `sw.job()` explicit context; the background analyzer thread with the bounded queue and never-raise guarantee ([ARCHITECTURE.md §7](./ARCHITECTURE.md)).

**Done when:** a third-party scraper changes exactly one line (client construction) and verdicts start appearing in logs; killing the analyzer thread mid-run leaves the scraper unaffected.

## 4. Phase 3 — Validation and drift (~1 week, 4–6 ed)

**Scope:** item schemas (declarative field specs), per-field fill rate over a rolling window, drift rules — volume drop, field emptiness, structure hash change — and freshness tracking per job. See [components/data-quality.md](./components/data-quality.md).

**Done when:** a job with a schema catches "`price` empty on 40% of items" and reports job status `drifted`; a fixture replay where the site was redesigned flips the structure hash.

## 5. Phase 4 — Storage, alerts, CLI (3–4 ed)

**Scope:** SQLite persistence (`runs`, `events` with embedded verdicts, job aggregates), retention policy, alert channels — logger, webhook, Telegram — and the CLI: `scrapewatch check page.html` (one-shot classification; doubles as a fixture-debugging tool) and `scrapewatch report` (terminal health summary incl. self-diagnostic counters). See [components/storage-alerts.md](./components/storage-alerts.md).

**Done when:** after a scraping session, `scrapewatch report` answers "when was this job's data last real?" without opening a database by hand.

## 6. Phase 5 — Public release 0.1 (2–3 ed)

**Scope:** product README (hero, 30-second quickstart, demo GIF), `examples/` for requests / httpx / Playwright / Scrapy, PyPI publish, launch posts (Show HN, r/webscraping) built around a real "caught a silent death" story.

**Done when:** `pip install scrapewatch` works for a stranger with no assistance.

---

## 7. Deferred and out of scope (v0.1)

| Item | Why deferred |
|---|---|
| TypeScript / Go SDKs | Core extraction path decided post-v0.1 ([ARCHITECTURE.md §8](./ARCHITECTURE.md)) |
| Sidecar server, dashboard, hosted service | Monetization layer; separate repo under FSL ([ADR-7](./contracts/decisions.md)) |
| Framework adapters (Scrapy middleware, Firecrawl wrapper, Crawlee hooks) | L1–L3 interceptors already cover most users; adapters follow demand |
| WASM playground on the project site | Marketing feature; depends on the Rust/WASM path |
| Anti-bot bypass features of any kind | Permanent, not deferred — positioning constraint ([ARCHITECTURE.md §1](./ARCHITECTURE.md)) |

## 8. External dependencies

Runtime: Python ≥3.10, stdlib-only core; `requests`/`httpx`/`playwright` are optional extras (interceptors import lazily — the package installs clean without any of them). Development: pytest, ruff, uv. Nothing else until a user demands it.
