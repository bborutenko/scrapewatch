# Scrapewatch Documentation

Scrapewatch is an open-source observability library for web scraping. It wraps any scraper — plain `requests`/`httpx` code, Playwright, or a browser agent — and tells you when the data you are collecting stops being real: anti-bot challenge pages served behind fake HTTP 200s, silent selector breakage after a site redesign, empty response shells, and drifting data quality. It is a diagnostic layer on top of your existing stack, not a scraping framework and not an anti-bot bypass (see [CONCEPTS.md](./CONCEPTS.md) for the vocabulary and [ARCHITECTURE.md §1](./ARCHITECTURE.md) for positioning).

> **Target state.** Everything in this folder describes the intended v0.1 design. No implementation exists yet. Anything not yet built carries the **(planned)** marker; anything explicitly postponed to a later cycle carries **(future)**. Facts that are decided rather than described live in [contracts/decisions.md](./contracts/decisions.md).

## Where this comes from

The product scope, architecture and roadmap were settled in the founding design discussions (November 2026). The binding decisions were distilled into the ADR log: [contracts/decisions.md](./contracts/decisions.md). If a doc and an ADR disagree, the ADR wins.

---

## How this is organized

```text
docs/
├── README.md                    ← you are here: map, reading order, conventions
├── CONCEPTS.md                  glossary: every domain term, defined once
├── ARCHITECTURE.md              cross-cutting design: core boundary, data flow, modes
├── roadmap.md                   phases 0–5 with estimates and "done when" gates
├── contracts/
│   ├── interfaces.md            the stable surface: Event/Verdict contract,
│   │                            public Python API, YAML rule format
│   └── decisions.md             ADR log — why the design is what it is
└── components/
    ├── core-engine.md           detector evaluation: rules → verdicts
    ├── interceptors.md          watch() over requests / httpx / Playwright
    ├── data-quality.md          schema validation, fill rate, drift, freshness
    └── storage-alerts.md        SQLite persistence, alert channels, CLI
```

---

## Where to start

- **New to the project?** Read [CONCEPTS.md](./CONCEPTS.md) first (10 minutes), then [ARCHITECTURE.md §1–§4](./ARCHITECTURE.md) for the big picture.
- **Going to write code?** [ARCHITECTURE.md §3](./ARCHITECTURE.md) (the core boundary — the one rule that must not be violated), then the [components/](./components/) doc for your subsystem, then [contracts/interfaces.md](./contracts/interfaces.md) so your code speaks the contract.
- **Wondering why it is built this way?** [contracts/decisions.md](./contracts/decisions.md) has one ADR per major decision, each with context and consequences.
- **Planning work?** [roadmap.md](./roadmap.md) — phases, estimates, and explicit out-of-scope list.

---

## File-by-file

### Root

| File | Purpose |
|---|---|
| [CONCEPTS.md](./CONCEPTS.md) | Glossary of domain terms. Terms are defined once here and reused verbatim everywhere else. |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | System design: package shape, pure core boundary, end-to-end data flow, operating modes, failure policy, and the future core-extraction paths. |
| [roadmap.md](./roadmap.md) | Phase 0–5 delivery plan with per-phase scope, effort estimates and "Done when" gates; deferred and out-of-scope items. |

### `components/` — how each subsystem works (target state)

| File | Purpose |
|---|---|
| [core-engine.md](./components/core-engine.md) | The pure rule engine: loading YAML rules, evaluating detectors against an Event, aggregating verdicts, snapshot testing over fixtures. |
| [interceptors.md](./components/interceptors.md) | The integration layer: `watch()` wrappers for `requests`, `httpx`, Playwright; job context propagation; the background analyzer and its never-crash guarantee. |
| [data-quality.md](./components/data-quality.md) | Everything that judges data rather than pages: item schemas, fill rate, drift rules (volume, emptiness, structure hash), freshness. |
| [storage-alerts.md](./components/storage-alerts.md) | SQLite persistence and retention, alert channels (log / webhook / Telegram), and the CLI (`scrapewatch check`, `scrapewatch report`). |

### `contracts/` — what is stable and why

| File | Purpose |
|---|---|
| [interfaces.md](./contracts/interfaces.md) | Part A: the Event/Verdict data contract (the future wire format). Part B: the public Python API surface. Part C: the YAML rule format specification. Breaking changes here are versioned, never silent. |
| [decisions.md](./contracts/decisions.md) | ADR log (ADR-1 … ADR-7): Python-only MVP, pure core, declarative rules, contract-first, transport-level interception, fire-and-forget, licensing. |

---

## Conventions

- One subsystem per file in `components/`; cross-cutting concerns live in the root docs. No doc duplicates another's scope.
- All docs are in English. Domain terms are defined once in [CONCEPTS.md](./CONCEPTS.md) and reused verbatim.
- Status vocabulary: **(planned)** = committed for v0.1 but not built; **(future)** = deliberately postponed beyond v0.1; unmarked structural descriptions refer to the agreed design. Once code lands, docs gain `verified against code on YYYY-MM-DD` notes.
- Architectural decisions are recorded as ADRs in [contracts/decisions.md](./contracts/decisions.md) — never re-litigated in prose elsewhere; link instead.
- Diagrams are ASCII inside ` ```text ` fences; no image or mermaid dependencies.
- Future phase folders (`docs/phase-N/`) will mirror this file set, and every file in a newer phase ends with a `## What changed since Phase N-1` section.
