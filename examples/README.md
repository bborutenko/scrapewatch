# Scrapewatch Examples

Run examples from project root:

```bash
cd examples

# Install dependencies
uv sync

# Run examples
uv run python src/watch_requests.py
uv run python src/watch_httpx.py
uv run python src/watch_playwright.py
uv run python src/guarded_retry.py
uv run python src/fetch_reactive.py
uv run python src/custom_rules.py
```

## Protocols

| Protocol | Description |
|----------|-------------|
| `watch()` | Passive observation — verdicts computed async |
| `guarded()` | Exception mode — raises SwBlocked/SwGarbage |
| `fetch()` | Reactive — verdict at decision point |

## Dependencies

Examples use `scrapewatch` from local path (../scrapewatch/core).
