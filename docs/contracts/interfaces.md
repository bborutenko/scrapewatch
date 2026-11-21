# Interfaces — Contracts

**Document type:** Contract — the stable public surface
**Status:** Target state, approved 2026-11-13; reactive mode added 2026-11-15 ([ADR-8](./decisions.md)) — skeleton implementation of the client layer has started
**Stability rule:** anything in this file is versioned. Breaking changes require a contract version bump and an ADR; they are never silent. CI will validate Events against the JSON Schema derived from Part A ([ADR-4](./decisions.md)).

Three parts: **A** — the data contract (`Event` / `Verdict`) that every subsystem, every future SDK, and the future server all speak; **B** — the public Python API for v0.1; **C** — the YAML rule format for detectors.

---

## Part A — The data contract

### A.1 `Event`

One observed HTTP response (or browser navigation). Built exclusively by interceptors (or the user via the explicit API); consumed exclusively by the engine.

| Field | Type | Required | Description |
|---|---|---|---|
| `schema_version` | `int` | yes | Event contract version; v0.1 ships `1`. |
| `url` | `str` | yes | Final URL after redirects. |
| `method` | `str` | no | HTTP method; default `"GET"`. |
| `status_code` | `int \| None` | no | HTTP status; `None` if the transport never got a response (e.g. Playwright navigation failure). |
| `headers` | `dict[str, str]` | no | Response headers, keys lowercased. |
| `content_type` | `str \| None` | no | Convenience copy of `content-type` header, without charset. |
| `body_sample` | `str` | no | Decoded prefix of the body, max 64 KiB — the only body content detectors may inspect. |
| `body_hash` | `str` | no | SHA-256 of the full raw body; enables change detection without keeping the body. |
| `body_length` | `int` | no | Raw body size in bytes. |
| `latency_ms` | `float \| None` | no | Time to response, if the transport exposes it. |
| `job` | `JobRef` | yes | Which job this event belongs to. |
| `items` | `list[dict] \| None` | no | Extracted records attached by the user for schema validation. |
| `captured_at` | `str` | yes | ISO-8601 UTC timestamp. |
| `meta` | `dict` | no | Interceptor-specific extras (e.g. Playwright `final_url`, redirect count). |

`JobRef`: `{ "name": str, "run_id": str, "schema_id": str | None }` — the schema itself is registered on the job (Part B), not repeated per event.

### A.2 `Verdict`

The engine's judgment about one Event.

| Field | Type | Required | Description |
|---|---|---|---|
| `status` | `enum` | yes | One of `ok`, `blocked`, `garbage`, `drifted`, `unknown` — `unknown` means Scrapewatch's own analysis failed and the event is unclassified (degradation, never an error; [ADR-8](./decisions.md)). Definitions: [CONCEPTS.md](../CONCEPTS.md). |
| `detector_id` | `str \| None` | yes | Rule that fired (`"cloudflare-challenge"`), `"schema"` for item validation, or `None` for `ok`. |
| `reason` | `str` | yes | Human-readable one-liner, e.g. `"Cloudflare interstitial behind HTTP 200"`. |
| `confidence` | `float` | yes | 0.0–1.0; derived from how many signatures matched; `1.0` for `ok` verdicts (no signatures involved). |
| `evidence` | `dict` | yes | Machine-readable match details: matched signature texts, offending item fields. |
| `event_hash` | `str` | yes | SHA-256 of the source Event's canonical JSON (`to_dict()`, sorted keys, compact separators) for correlation in storage. |

Aggregation rule when several detectors fire on one Event: highest `severity` wins; ties broken by verdict precedence `blocked > garbage > drifted > ok`.

### A.3 Versioning policy

- Contract version lives in `Event.schema_version`; it changes only incompatibly with an ADR and a migration note.
- Additive changes (new optional fields) do not bump the version.
- Every future SDK (TS, Go, Rust core) generates or validates against the JSON Schema built from this document; the schema file is the single source of truth, this doc is its human-readable form.

---

## Part B — Public Python API (v0.1)

Entry points come in two families ([ADR-8](./decisions.md)): **passive** (B.1–B.4 — observe with zero code change, verdicts delivered asynchronously) and **reactive** (B.5–B.6 — verdict delivered synchronously at the decision point, so the scraper can act on it):

### B.1 `watch()` — wrap a client

```python
import scrapewatch as sw

# requests
session = sw.watch(requests.Session(), job="ebay-prices")

# httpx (sync and async) — planned Phase 2
client = sw.watch(httpx.Client(), job="ebay-prices")
aclient = sw.watch(httpx.AsyncClient(), job="ebay-prices")

# Playwright — planned Phase 2
browser = sw.watch(playwright.chromium.launch(), job="agent-crawler")
```

Optional arguments: `schema=` (see B.4), `rules=[path, ...]` (extra rule files).

Configuration is handled via `sw.configure()`:

```python
# Configure before watch()
sw.configure(
    db_path="scrapewatch.db",      # SQLite database path
    queue_limit=10_000,            # Max events in queue
    shutdown_timeout=10.0,         # Graceful shutdown timeout
    batch_size=50,                 # Storage batch size
)

# Settings apply globally to all watch() calls
session = sw.watch(requests.Session(), job="ebay-prices")
```

Returns the same object, wrapped: everything the scraper did before keeps working identically.

### B.2 `job()` — explicit context (level L3)

```python
with sw.job("visa-slots", schema=SlotSchema) as j:
    resp = my_exotic_client.fetch(url)
    j.observe(url, resp)        # hand over the response
    j.items(rows)               # hand over extracted data
```

`j.observe` accepts a `requests`/`httpx` Response, raw `(status_code, headers, body_bytes)`, or a pre-built `Event`.

### B.3 `check()` — one-shot classification

```python
verdict = sw.check(html, url="https://example.com", status_code=200)
# Verdict(status='blocked', detector_id='cloudflare-challenge', ...)
```

The same code path powers `scrapewatch check` CLI. Deliberately synchronous — it is a debugging tool, not an interceptor.

### B.4 Item schema declaration

```python
schema = sw.Schema({
    "title": {"type": "str", "required": True},
    "price": {"type": "float", "required": True, "range": [0, 10_000_000]},
    "sku":   {"type": "str", "required": False},
})
```

Supported checks in v0.1: `type` (`str`, `int`, `float`, `bool`), `required`, `range` (numeric), `min_length`/`max_length` (strings), `enum`. Semantics (fill rate, drift) are defined in [components/data-quality.md](../components/data-quality.md).

### B.5 `fetch()` — reactive request context

```python
with sw.fetch(session.get, url, job="ebay-prices") as r:
    if r.verdict.status == "blocked":
        rotate_proxy()
        r.retry()
    elif r.verdict.status == "garbage":
        skip(url)
    else:
        r.items(extract(r.response))    # schema validation + recorded history
```

- `sw.fetch(fn, *args, job=..., **kwargs)` — `fn` is the client's request method (`session.get`, `client.get`, …); the first attempt executes inside the context.
- The context object exposes `.response`, `.verdict` (computed synchronously before the block body runs), `.retry()` (re-execute `fn`) and `.items(rows)`.
- `verdict.status == "unknown"` means Scrapewatch itself failed to classify — treat as unclassified, never as an error ([ADR-8](./decisions.md)).
- The event is recorded like any passive one: reacting now does not lose history.

### B.6 `guarded()` — verdict-as-exception

```python
session = sw.guarded(requests.Session(), job="ebay-prices")

@retry(retry=retry_if_exception_type(sw.SwBlocked), stop=stop_after_attempt(3))
def get_listing(url):
    return session.get(url)   # raises sw.SwBlocked on challenge pages — including fake-200s
```

- Wraps a client exactly like `watch()` (verdicts still recorded), but `blocked` verdicts raise `sw.SwBlocked` and `garbage` verdicts raise `sw.SwGarbage`.
- Designed for retry libraries (tenacity et al.): a fake-200 becomes a first-class retry trigger with one line.
- Exceptions carry the `Verdict`; the response is available as `exc.response`.
- Strictly opt-in: the default `watch()` never raises ([ADR-6](./decisions.md)).

---

## Part C — YAML rule format

Detectors are data, not code ([ADR-3](./decisions.md)). Canonical files live in the repo-root `rules/` directory; users can add their own and pass them via `watch(..., rules=[...])`.

### C.1 Full example

```yaml
# rules/cloudflare-challenge.yaml
id: cloudflare-challenge
name: Cloudflare challenge / interstitial
verdict: blocked
severity: high
reference: https://developers.cloudflare.com/waf/
match:
  status_hint: [403, 429, 503]     # narrows evaluation, never sufficient alone
  any_of:
    - title_re:
        - "Just a moment"
        - "Attention Required! | Cloudflare"
    - body_re:
        - "cdn-cgi/challenge-platform"
        - "cf-browser-verification"
        - "__cf_chl_jschl_tk__"
    - script_src_re:
        - "challenges\\.cloudflare\\.com"
```

### C.2 Field reference

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | `str` | yes | Stable identifier; doubles as the fixtures directory name (`tests/fixtures/<id>/`). |
| `name` | `str` | yes | Human-readable label used in reasons and reports. |
| `verdict` | `enum` | yes | `blocked` or `garbage` — what the event is classified as when this detector fires. |
| `severity` | `enum` | yes | `low` / `medium` / `high`; resolves multi-match conflicts (A.2). |
| `reference` | `url` | no | Documentation link for the protection/pattern. |
| `match.status_hint` | `list[int]` | no | Statuses where this detector is *likely*; a match inside the hint raises confidence, absence lowers it — but body/title evidence remains authoritative (fake-200 is the whole point). |
| `match.any_of` | `list[group]` | no | Fires if **any** group matches. |
| `match.all_of` | `list[group]` | no | Fires only if **all** groups match (for multi-signal patterns). |

Group primitives ( combinable within one group object):

| Primitive | Matches against |
|---|---|
| `title_re` | Regex list against the extracted `<title>` (case-insensitive). |
| `body_re` | Regex list against `Event.body_sample` only. |
| `script_src_re` | Regex list against all `<script src=...>` values. |
| `header` | Exact header assertions: `{name: value_re}`. |

### C.3 Combination and confidence semantics

1. Within a group, a primitive fires when **any** of its regexes matches.
2. A group fires when **any** (for `any_of`) / **all** (for `all_of`) of its primitives fire.
3. A detector fires when its `any_of` OR `all_of` logic is satisfied.
4. `confidence = 0.5 + 0.5 * (matched_primitives / total_primitives_in_fired_groups)`, capped at 1.0; adjusted ±0.1 by `status_hint` agreement.
5. Regexes compile once at rule-load time; invalid regexes fail rule loading loudly (a broken detector must never silently disable itself — see [ADR-6](./decisions.md)).
