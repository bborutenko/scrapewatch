# Scrapewatch Examples

This directory contains examples for all three protocols:

## Protocols

### 1. watch() — Passive Observation
Wrap a client and observe all traffic. Verdicts are computed asynchronously.

```bash
python watch_requests.py
python watch_httpx.py
python watch_playwright.py
```

### 2. guarded() — Verdict-as-Exception
Wrap a client that raises `SwBlocked`/`SwGarbage` on bad verdicts.
Designed for retry integration.

```bash
python guarded_retry.py
```

### 3. fetch() — Reactive Context
Execute a request and get the verdict synchronously.
React at the decision point (rotate proxy, retry, skip).

```bash
python fetch_reactive.py
```

## Custom Rules

Override packaged rules or add your own detectors:

```bash
python custom_rules.py
```

## Requirements

```bash
pip install scrapewatch[requests]    # For requests examples
pip install scrapewatch[httpx]       # For httpx examples  
pip install scrapewatch[playwright]  # For Playwright examples
pip install scrapewatch[all]         # All clients + tenacity
```

## HTTP Testing

Examples use httpbin.org for testing. For local testing:

```bash
# Install local test server (optional)
pip install pytest-httpserver

# Or use httpbin Docker
docker run -p 80:80 kennethreitz/httpbin
```
