# Interceptors — The Integration Layer

**Document type:** Component design — target state
**Status:** Phase 2 — in progress: client dispatch (`client.py`), the requests interceptor and the shared capture path (`base.py`: Event assembly, bounded queue, background analyzer with verdict logging) are wired to the engine — verified against code on 2026-11-19. httpx/Playwright, `fetch.py`/`guarded.py`, storage and alert dispatch remain (planned). Current skeleton lives in a nested uv project (`scrapewatch/core/src/scrapewatch/`); it is flattened to the layout below during Phase 0 cleanup.
**Depends on:** [core-engine.md](./core-engine.md) (produces its Events), [ADR-5](../contracts/decisions.md) (transport-level interception), [ADR-6](../contracts/decisions.md) (fire-and-forget), [ADR-8](../contracts/decisions.md) (reactive mode)

## 1. Role

Interceptors are the only part of Scrapewatch that touches user transport objects. Each one wraps a specific client, captures every response that passes through it, converts it into an `Event`, and enqueues it for the background analyzer. They contain **zero** business logic — a rule of equal rank with the pure-core boundary: if an interceptor ever needs to "check" something, the check belongs in the core.

## 2. Current layout

| Path | Wraps | Mechanism |
|---|---|---|
| `scrapewatch/interceptors/requests_interceptor.py` | `requests.Session` | subclass wrapping `request()`/`send()` — captures the final `Response` |
| `scrapewatch/core/analyzer.py` | — | shared: Event assembly (`build_event`), SyncAnalyzer, AsyncAnalyzer with bounded queue, never-raise wrapper |

**Planned (Phase 2):**

| Path | Wraps | Mechanism |
|---|---|---|
| `scrapewatch/interceptors/httpx.py` | `httpx.Client` / `httpx.AsyncClient` | native `event_hooks={"response": [...]}`; async variant enqueues without awaiting |
| `scrapewatch/interceptors/playwright.py` | Playwright `Browser` / `BrowserContext` | wraps context creation; `page.on("response")` + navigation listeners |
| `scrapewatch/interceptors/fetch.py` | any request callable | reactive context: run `fn`, compute the verdict synchronously, expose `.response`/`.verdict`/`.retry()` ([ADR-8](../contracts/decisions.md)) |
| `scrapewatch/interceptors/guarded.py` | `requests`/`httpx`/Playwright clients | like `watch()`, but raises `SwBlocked`/`SwGarbage` on bad verdicts (opt-in, [ADR-8](../contracts/decisions.md)) |

All third-party imports are lazy: installing `scrapewatch` without `requests`/`httpx`/`playwright` must remain clean; the extra is only imported when `watch()` meets that type ([ADR-5](../contracts/decisions.md)).

## 3. The `watch()` contract

```python
client = sw.watch(any_supported_client, job="ebay-prices",
                  schema=..., rules=[...], db=..., alerts=[...])
```

- Returns an object the user uses exactly like the original — same methods, same types, same exceptions. Scrapewatch adds no behavior to the transport, it only observes.
- One wrap, one job: all traffic through the wrapped client belongs to that job. For multi-job scrapers, wrap one client per job or use the explicit `sw.job()` API.
- Double-wrap protection: `watch(watch(x))` logs a warning and returns the already-wrapped object unchanged.

The reactive siblings (`sw.fetch()`, `sw.guarded()`) deliberately break the "no behavior change" rule — that is their job: they hand the verdict to the caller synchronously so the scraper can react. Full API: [interfaces.md B.5–B.6](../contracts/interfaces.md). Implementation note: `fetch.py` and `guarded.py` reuse the same Event assembly and the same analyzer queue — they only *also* run `engine.observe()` inline and surface the result.

## 4. Event assembly (per captured response)

| Event field | Source by client |
|---|---|
| `url` | final URL (after redirects); Playwright: `response.url` |
| `status_code` / `headers` / `content_type` | response object; `None` on transport failure (still an Event — failures are signal too) |
| `body_sample` / `body_hash` / `body_length` | decoded first 64 KiB / SHA-256 of full body / byte size — never the full body in memory beyond the sample |
| `latency_ms` | requests/httpx: measured around the call; Playwright: request→response timestamps where available |
| `meta` | client-specific extras (redirect count, Playwright `final_url`, frame info) |

Body-size guard: responses over a configurable cap (default 10 MB) contribute hash+length but no sample — the analyzer does not need megabytes to spot a challenge page.

## 5. The background analyzer

```text
caller thread                         analyzer thread
─────────────                         ───────────────
response arrives
  └─ build Event        (µs)
      └─ queue.put(event)  ─────────▶  event = queue.get()
      └─ return to scraper               verdict = engine.observe(event)
      (never waits)                      storage.write(verdict)
                                          data_quality.evaluate(job)
                                          alerts.dispatch(...)
```

- Bounded `queue.Queue` (default 10,000). On saturation, `submit()` blocks the caller (backpressure) until space is available — no events are dropped (see [ADR-6](../contracts/decisions.md)).
- The analyzer is a daemon thread started lazily on first `watch()`/`job()`; process exit never waits on it.
- Every analyzer iteration is wrapped in a catch-all: exceptions increment `analyzer_errors`, log at WARNING, and processing continues with the next event.
- Async users (`httpx.AsyncClient`, async Playwright): the queue and analyzer remain synchronous/threaded — `asyncio` code just enqueues from the event loop without `await`.

## 6. Testing strategy

- **Never-raise fault injection:** monkeypatch `engine.observe`, `storage.write`, `alert.dispatch` to raise; assert the wrapped client still returns correct responses and counters incremented (the ADR-6 acceptance test from [roadmap.md Phase 2](../roadmap.md)).
- **Behavioral parity:** recorded sessions run through wrapped and unwrapped clients must produce identical user-visible results.
- **Version drift:** interceptors use capability checks (`hasattr`, documented API surface only), tested against the oldest supported version of each client.

## 7. Open questions (Phase 2)

- httpx streaming responses (`client.stream()`): sample the stream prefix or skip body capture? (requests resolved 2026-11-19: an unread `stream=True` response contributes no body — `meta.body_skipped` — because reading `.content` would drain the socket; ADR-6 outranks detection.)
- Playwright: attach at `Browser` or `BrowserContext` level by default? (Current answer: context — cleaner multi-page semantics.)
- Should transport-level exceptions (connection refused, DNS) become Events with `status_code=None` now, or after Phase 1 ships? (Current answer: now — they are blocked-adjacent signal.)
