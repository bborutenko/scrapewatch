# Core Engine — Detector Evaluation

**Document type:** Component design — target state
**Status:** (planned) Phase 1 — no implementation exists yet
**Depends on:** [contracts/interfaces.md](../contracts/interfaces.md) (Event/Verdict contract, YAML rule format)

## 1. Role

The core engine is the entire classification business logic of Scrapewatch: it turns an `Event` into a `Verdict` by evaluating YAML detector rules, and nothing else. It is the module the [pure-core boundary](../ARCHITECTURE.md) ([ADR-2](../contracts/decisions.md)) protects: no I/O, no threads, no framework imports, stdlib-only (a YAML parser is the single allowed dependency — vendored or `PyYAML`).

## 2. Planned layout

| Path | Responsibility |
|---|---|
| `scrapewatch/core/event.py` | `Event`, `JobRef` dataclasses — generated-from/validated-against the contract schema ([ADR-4](../contracts/decisions.md)) |
| `scrapewatch/core/verdict.py` | `Verdict` dataclass + aggregation rule (highest severity, precedence `blocked > garbage > drifted > ok`) |
| `scrapewatch/core/rules.py` | Rule loading and compilation: YAML files → compiled detector set |
| `scrapewatch/core/engine.py` | `Engine.observe(event: Event) -> Verdict` — the one public entry point |
| `rules/*.yaml` | Canonical detector rules (data, packaged with the wheel) |

## 3. Rule loading

1. On `Engine` construction, load the packaged `rules/` directory, then any user-supplied rule files (`watch(..., rules=[...])`) — user rules may override canonical ones by `id` (lets users tune signatures for their region/site without forking).
2. Compile all regexes immediately; invalid regex aborts loading with a loud error naming the file and pattern — a broken detector must fail visibly, never silently disable itself.
3. Extract `<title>` and `script src` values from `body_sample` once per event (lightweight stdlib HTML parsing, not a full DOM tree — the sample is capped at 64 KiB by the contract).

## 4. Evaluation pipeline

Order is deliberate — cheapest discriminators first, so healthy responses cost almost nothing:

```text
Event ─▶ 1. header/title matchers        (string ops over tiny data)
      ─▶ 2. status_hint narrowing        (skip detectors whose hint strongly disagrees? no —
      │                                     hint only adjusts confidence, see Part C.4)
      ─▶ 3. body_re / script_src_re      (regex over the 64 KiB sample)
      ─▶ 4. item validation (if items)   (delegates to data-quality checks, same call)
      ─▶ 5. aggregate firing detectors ─▶ Verdict
```

An event with zero detector hits and passing item validation returns `Verdict(status="ok", detector_id=None, ...)` in a single cheap pass.

## 5. First detector set (Phase 1 scope)

| Detector id | Verdict | Severity | Primary signatures |
|---|---|---|---|
| `cloudflare-challenge` | blocked | high | title "Just a moment…", `cdn-cgi/challenge-platform`, `challenges.cloudflare.com` |
| `datadome` | blocked | high | `datadome` cookies/scripts, `geo.captcha-delivery.com` |
| `akamai` | blocked | high | Akamai BMP interstitial markers |
| `kasada` | blocked | high | Kasada challenge payloads (`/fp` endpoints, obfuscated props) |
| `captcha-wall` | blocked | medium | generic: reCAPTCHA / hCaptcha / Turnstile iframes as primary content |
| `empty-spa-shell` | garbage | medium | body under ~2 KB with empty mount node + bundle scripts, no text |
| `login-wall` | garbage | medium | redirect chain ending at `/login`/`/signin`, auth form as primary content |
| `geo-block` | garbage | medium | region-unavailable copy patterns |
| `soft-404` | garbage | low | "not found" copy with 200 status |

Signature lists are living data in `rules/` — the table above records intent, the YAML records truth.

## 6. Testing strategy

- **Fixtures are the spec.** `tests/fixtures/<detector-id>/*.html` holds saved snapshots of real challenge/placeholder pages (collected legally, for testing). A detector passes when every fixture maps to its verdict and nothing else fires.
- **Golden verdicts:** `tests/fixtures/cases.yaml` maps `fixture → expected Verdict(status, detector_id)`; CI replays the whole corpus on every change.
- **Negative corpus:** fixtures of healthy pages (incl. pages that *contain* a Turnstile widget but are real content) must stay `ok` — false positives are treated as bugs of equal severity to false negatives.
- Fault-injection for ADR-6 lives in the interceptors layer, not here — the core has nothing to fail at by construction.

## 7. Open questions (to resolve in Phase 1 implementation)

- Exact `title` extraction under malformed HTML — fallback to first `<title>…</title>` regex slice?
- Should `status_hint` mismatch ever *suppress* a strong body+title double match? (Current answer: no — hint adjusts confidence only.)
- Minimum corpus size per detector before it ships in a release (proposal: ≥ 3 real fixtures each).
