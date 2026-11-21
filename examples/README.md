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

## Rules Configuration

Rules are auto-loaded from `scrapewatch.toml`:

```toml
[scrapewatch]
rules_dir = "rules"
```

**Option 1: Global config file**
```toml
# scrapewatch.toml
[scrapewatch]
rules_dir = "rules"
```

**Option 2: Environment variables**
```bash
export SCRPAPEWATCH_RULES_DIR=rules
```

**Option 3: In code**
```python
sw.configure(rules_dir="rules")
```

**Option 4: Per-client**
```python
session = sw.watch(
    requests.Session(),
    job="test",
    rules=["custom.yaml"]
)
```

## Dependencies

Examples use `scrapewatch` from local path (../scrapewatch/core).
