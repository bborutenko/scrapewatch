# Concepts — Scrapewatch Glossary

**Document type:** Reference — domain vocabulary
**Status:** Target state, approved 2026-11-13
**Audience:** everyone; terms defined here are reused verbatim across all docs and (later) code identifiers

Terms are grouped thematically. Each term is defined exactly once; other docs link here instead of re-explaining.

## Product & naming

| Term | Definition |
|---|---|
| **Scrapewatch** | The product (capitalized). An open-source observability library for web scraping. |
| **scrapewatch** | The Python package and repository name. |
| **user scraper** | The scraper being observed — the user's own code, whatever framework it uses. Scrapewatch never replaces it, only wraps it. |
| **job** | One logical scraping unit the user wants to monitor: e.g. `ebay-prices` or `visa-slots`. A job has a name, an optional item schema, and accumulates events and aggregates. |
| **run** | One execution of a job (`job` + `run_id`), typically one process launch. |

## The observation model

| Term | Definition |
|---|---|
| **Event** | The unit of observation: everything Scrapewatch knows about one HTTP response (or Playwright navigation) — URL, status, headers, body sample and hash, latency, job reference, optionally extracted items. Full field list: [contracts/interfaces.md Part A](./contracts/interfaces.md). |
| **Verdict** | The engine's judgment about one Event: a `status` (`ok`, `blocked`, `garbage`, `drifted`) plus `detector_id`, `reason`, `confidence` and machine-readable evidence. |
| **`ok`** | The response looks like the real page and the data looks healthy. |
| **`blocked`** | The response is an anti-bot artifact: challenge page, captcha wall, or access denied, regardless of the HTTP status it arrived with. |
| **`garbage`** | The response is technically a page but not the page the job expects: empty SPA shell, login/redirect wall, geo-block page, soft-404. |
| **`drifted`** | The page may render fine but the *data shape* changed: schema violations, collapsing fill rate, volume drop, structure hash change. Arises mostly from job-level aggregation (see [data-quality.md](./components/data-quality.md)), not from single-response detectors. |
| **fake-200** | The core failure mode Scrapewatch exists for: an anti-bot or placeholder page delivered with HTTP 200, so status-code monitoring sees "success" while the pipeline stores garbage. |

## Failure taxonomy (what detectors look for)

| Term | Definition |
|---|---|
| **challenge page** | An interstitial from a bot-protection vendor (Cloudflare, DataDome, Akamai, Kasada, …) that either waits for JavaScript or demands a puzzle. Usually served instead of the target page, often with status 403/429/503 — but also with 200. |
| **captcha wall** | A page whose primary content is a captcha form (reCAPTCHA, hCaptcha, Turnstile, vendor-specific). Subcase of `blocked`. |
| **empty SPA shell** | A valid HTML document that contains only the app skeleton (`<div id="root"></div>` + bundles) because rendering was blocked or failed. Subcase of `garbage`. |
| **soft-404** | A "not found" or error page served with a 200 status. Subcase of `garbage`. |
| **geo-block page** | A region-unavailable notice served to the scraper's IP/region. Subcase of `garbage`. |
| **login wall** | A redirect to sign-in where data was expected: the session expired or the content moved behind auth. Subcase of `garbage`. |
| **schema drift** | Extracted items stop conforming to the job's schema — usually the site was redesigned and selectors silently return `None`. Detected by the data-quality subsystem, reported as `drifted`. |
| **freshness** | How long ago the job last saw a genuinely healthy state (last `ok` event / last successful item extraction). The answer to "when was our data last real?". |

## Rules & detectors

| Term | Definition |
|---|---|
| **detector** | One named classification of a response pattern, e.g. `cloudflare-challenge`. Declared as data in a YAML rule file; the engine interprets it. See [contracts/interfaces.md Part C](./contracts/interfaces.md). |
| **rule file** | A YAML file containing one or more detectors. Canonical rules ship in the repo-root [`rules/`](../rules/) directory and are packaged with the wheel; users can add their own. |
| **signature** | A single matching primitive inside a detector: a title regex, body regex, script-src pattern, or header assertion. |
| **matcher group** | Signatures combined with `any_of` / `all_of` logic inside a detector; a detector fires when its group logic is satisfied. |
| **severity** | Detector attribute (`low` / `medium` / `high`) used when multiple detectors fire on one event: the highest-severity verdict wins. |

## Data quality

| Term | Definition |
|---|---|
| **item schema** | A declarative description of what one extracted record must look like: field names, types, required/optional, value ranges. Format: [contracts/interfaces.md Part B](./contracts/interfaces.md). |
| **item** | One extracted record (a dict of field → value) attached to an Event for validation. |
| **fill rate** | Share of recent items in which a given field is present and non-null. A field whose fill rate collapses from 100% to 60% is schema drift in progress. |
| **drift rule** | A job-level predicate over aggregates: volume drop, field emptiness, structure change. When one fires, the job's state becomes `drifted`. Full list: [data-quality.md](./components/data-quality.md). |
| **structure hash** | A hash of the normalized DOM tag sequence of a page. Site redesigns change the hash even when every response is 200/`ok`. |
| **baseline** | The rolling reference window (recent healthy activity) against which drift rules compare the present. |

## Integration

| Term | Definition |
|---|---|
| **interceptor** | The adapter that captures responses from a specific client (`requests.Session`, `httpx.Client`, Playwright) and turns them into Events. The only part of Scrapewatch that touches user transport objects. See [interceptors.md](./components/interceptors.md). |
| **`watch()`** | The one-function integration: `session = sw.watch(requests.Session(), job="...")` — after which every response flows through Scrapewatch. |
| **in-process mode** | The only v0.1 operating mode: engine, storage and alerting run inside the user's scraper process (background thread + SQLite). No infrastructure to deploy. |
| **sidecar mode (future)** | A separate Scrapewatch server receiving Events over HTTP; multi-scraper dashboards and team alerting. Deliberately out of scope for v0.1 — see [ADR-1](./contracts/decisions.md). |
| **fire-and-forget** | The interception policy: analysis is asynchronous, buffered, and failure-tolerant. Any Scrapewatch error is swallowed and logged; observability must never break the scraper it observes. See [ADR-6](./contracts/decisions.md). |
| **background analyzer** | The worker thread inside the user's process that drains the event queue: runs the engine, persists verdicts, evaluates drift rules, dispatches alerts. |
