# scrapewatch

Open-source observability for web scrapers: catches challenge pages behind fake 200s, schema drift, and silent data failures. Works with Scrapy, Playwright, Firecrawl, Crawl4AI, and browser agents.

> **Status:** in development — the [documentation](./docs/README.md) describes the target v0.1, the client layer is being implemented. Not yet installable (`pip install scrapewatch` arrives with the 0.1 release).

```python
import scrapewatch as sw

session = sw.watch(requests.Session(), job="ebay-prices")
# ...scrape as usual — scrapewatch quietly classifies every response
# and tells you when the data stops being real
```

Verdicts can also be consumed at the decision point, so your scraper can react — rotate a proxy, retry, skip:

```python
session = sw.guarded(requests.Session(), job="ebay-prices")

@retry(retry=retry_if_exception_type(sw.SwBlocked))   # tenacity
def get(url):
    return session.get(url)   # a challenge page raises SwBlocked — even behind a fake 200
```

## Why

Scrapers die silently. Anti-bot systems serve challenge pages behind fake HTTP 200s, sites get redesigned and selectors return `None` — while the pipeline keeps "successfully" storing garbage for weeks. Scrapewatch wraps your existing scraper (one changed line) and reports blocked pages, broken extraction, and data drift before your database fills with junk.

It is a diagnostic layer, not a framework: it never bypasses protections, never replaces your stack, and can never break your scraper (fire-and-forget by design).

## Documentation

Full design documentation lives in [`docs/`](./docs/):

- [docs/README.md](./docs/README.md) — start here: map and reading guide
- [docs/CONCEPTS.md](./docs/CONCEPTS.md) — glossary of domain terms
- [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) — system design and the core boundary
- [docs/roadmap.md](./docs/roadmap.md) — build phases 0–5
- [docs/contracts/](./docs/contracts/) — the Event/Verdict contract, public API, YAML rule format, and the ADR log

## License

Apache-2.0 — see [LICENSE](./LICENSE).
