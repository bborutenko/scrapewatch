# Scrapewatch

**Open-source observability for web scrapers.**

Catches challenge pages behind fake 200s, schema drift, and silent data failures — before your database fills with garbage.

## Why

Scrapers die silently:

- Anti-bot systems serve challenge pages with **HTTP 200** — your scraper thinks everything is fine
- Sites get redesigned and selectors return `None` — but the pipeline keeps running  
- Data quality drifts for weeks before anyone notices

Scrapewatch wraps your existing scraper (one line change) and tells you when the data stops being real.

**It's a diagnostic, not a framework:**
- Never bypasses protections
- Never replaces your stack
- Can never break your scraper (fire-and-forget by design)

## Installation

```bash
# Install with the HTTP client you use:
pip install scrapewatch[requests]   # or
pip install scrapewatch[httpx]       # or  
pip install scrapewatch[playwright]  # or
pip install scrapewatch[all]         # everything
```

## Quick Start

### Passive Mode (watch)

Wrap your client once — all traffic is observed silently:

```python
import requests
import scrapewatch as sw

# Before:
session = requests.Session()

# After:
session = sw.watch(requests.Session(), job="ebay-prices")

# Use exactly like before — scrapewatch runs in background
response = session.get("https://example.com")
```

Every response is classified:
- `ok` — real page, healthy data
- `blocked` — challenge page, captcha, access denied (even behind HTTP 200)
- `garbage` — empty shell, login wall, geo-block, soft-404
- `drifted` — page renders fine but data shape changed (schema violations)

### Reactive Mode (guarded) — Phase 2

Get verdicts at the decision point so your scraper can react:

```python
from tenacity import retry, retry_if_exception_type

session = sw.guarded(requests.Session(), job="ebay-prices")

@retry(retry=retry_if_exception_type(sw.SwBlocked))
def get_listing(url):
    return session.get(url)  # raises SwBlocked on challenge pages
```

## Supported Clients

| Library | Sync | Async | Notes |
|---|---|---|---|
| `requests` | ✅ | — | Full support |
| `httpx` | ✅ | ✅ | Full support |
| `playwright` | ✅ | ✅ | Browser & BrowserContext |

## How It Works

```
┌─────────────────────────────────────────────────────────────┐
│                      YOUR SCRAPER                            │
│              (requests / httpx / Playwright)                 │
└─────────────────────┬───────────────────────────────────────┘
                      │ response passes through unchanged
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                  SCRAPEWATCH                                 │
│   1. Capture URL, status, headers, body sample              │
│   2. Classify with detector rules (YAML)                    │
│   3. Store verdict + trigger alerts                         │
│                                                              │
│   Runs in background thread — never blocks your scraper      │
└─────────────────────────────────────────────────────────────┘
```

**Key properties:**
- **Fire-and-forget**: No scrapewatch error ever propagates into user code
- **Bounded queue**: 10,000 events max; backpressure on saturation
- **Zero business logic in interceptors**: Pure observation layer

## Built-in Detectors

Scrapewatch ships with detectors for common anti-bot patterns:

- `cloudflare-challenge` — Cloudflare interstitials and Turnstile
- More detectors coming in Phase 1

Add your own detectors via YAML files:

```python
session = sw.watch(
    requests.Session(), 
    job="ebay-prices",
    rules=["/path/to/my-detectors.yaml"]
)
```

## Examples

### requests

```python
import requests
import scrapewatch as sw

session = sw.watch(requests.Session(), job="product-prices")

# Normal usage — everything is observed
for url in product_urls:
    response = session.get(url)
    # Process response...
```

### httpx (async)

```python
import asyncio
import httpx
import scrapewatch as sw

async def scrape():
    client = sw.watch(httpx.AsyncClient(), job="product-prices")
    
    for url in product_urls:
        response = await client.get(url)
        # Process response...

asyncio.run(scrape())
```

### Playwright

```python
from playwright.sync_api import sync_playwright
import scrapewatch as sw

with sync_playwright() as p:
    browser = p.chromium.launch()
    watched = sw.watch(browser, job="product-prices")
    
    context = watched.new_context()
    page = context.new_page()
    
    page.goto("https://example.com")
    # All responses are observed...
```

## API Reference

### `sw.watch(client, job, rules=None)`

Wrap a client for passive observation.

- `client`: `requests.Session`, `httpx.Client`, `httpx.AsyncClient`, Playwright `Browser`, or `BrowserContext`
- `job`: Job name (string)
- `rules`: Optional list of custom rule file paths

Returns wrapped client — use exactly like the original.

### `sw.guarded(client, job, rules=None)` — Phase 2

Like `watch()`, but raises `sw.SwBlocked` or `sw.SwGarbage` on bad verdicts.

### `sw.fetch(fn, *args, job, rules=None, **kwargs)` — Phase 2

Context manager for reactive requests with verdict access.

## Documentation

- [Design docs](https://github.com/bogdanborutenko/scrapewatch/tree/main/docs) — architecture, concepts, roadmap
- [API reference](https://github.com/bogdanborutenko/scrapewatch/blob/main/docs/contracts/interfaces.md)

## Status

**v0.1 in development:**
- ✅ Core engine and verdict classification
- ✅ requests interceptor
- ✅ httpx interceptor (sync + async)
- ✅ Playwright interceptor (sync + async)
- 🔜 Reactive modes (guarded, fetch)
- 🔜 Schema validation and drift detection
- 🔜 Storage and alerts

## License

Apache-2.0 — see [LICENSE](https://github.com/bogdanborutenko/scrapewatch/blob/main/LICENSE).
