# scrapewatch

Open-source observability for web scrapers: catches challenge pages behind
fake 200s, schema drift, and silent data failures.

Status: design phase — implementation is starting. Design docs live in the
[repository docs](../../docs/README.md).

```python
import scrapewatch as sw

session = sw.watch(requests.Session(), job="ebay-prices")
# scrape as usual — scrapewatch quietly classifies every response
```

Client libraries are optional extras: `pip install scrapewatch[requests]`,
`scrapewatch[httpx]`, `scrapewatch[playwright]`, or `scrapewatch[all]`.
