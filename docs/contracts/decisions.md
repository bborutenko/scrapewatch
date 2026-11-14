# Architectural Decision Record — Scrapewatch

**Document type:** ADR log
**Status:** Decisions 1–7 accepted 2026-11-13; no implementation exists yet

Format: each ADR carries **Status** / **Context** / **Decision** / **Consequences**. ADRs are never edited to change their mind — a superseding ADR is added instead. If an ADR and any other doc disagree, the ADR wins.

---

## ADR-1: Python-only MVP; polyglot core deferred

**Status:** Accepted, 2026-11-13

### Context

The product ultimately wants SDKs beyond Python (TS scraping is large; Go exists). Options: Rust core + PyO3/napi-rs/WASM from day one; Go core + HTTP server; or Python-only first. The founder is a solo developer whose fastest language is Python; the project has zero users and must reach a convincing v0.1 quickly.

### Decision

v0.1 is a single Python library: pure core + interceptors + SQLite storage, in-process mode only. No server, no foreign-language core, no CI build matrix beyond Python. The polyglot split (Rust core, Go server, or WASM) is an explicit post-v0.1 decision, kept cheap by ADR-2 and ADR-4.

### Consequences

- Fastest possible path to first users and real feedback; one language to test, package, and document.
- The "zero-infrastructure" onboarding mode (in-process) is exactly the Python offering; TS/Go users get nothing until the split happens.
- Risk accepted: if the Rust/Go port is ever done late and hastily, contract drift is possible — mitigated by ADR-4 (contract-first) and by keeping the core small.

---

## ADR-2: Pure core boundary — `engine.observe(Event) → Verdict`, no I/O

**Status:** Accepted, 2026-11-13

### Context

The original architecture debate (in-process library vs HTTP sidecar vs embedded engine) risks baking business logic into whatever shell ships first — HTTP handlers, Playwright callbacks, CLI code — making every later mode a rewrite.

### Decision

All classification business logic lives in `scrapewatch/core` as a pure library: no network, no disk, no threads, no framework imports. Its public surface is one function, `engine.observe(event: Event) -> Verdict`. Interceptors, storage, alerts, CLI, and any future server are thin shells that build Events and consume Verdicts.

### Consequences

- The engine is trivially unit-testable; the snapshot fixture corpus doubles as regression suite and README demo material.
- Porting the core to Rust/WASM/Go later becomes a mechanical translation of one module.
- Shells stay deliberately dumb; any temptation to "just add this check inside the interceptor" is a smell that the core is missing a capability.

---

## ADR-3: Declarative YAML rules — detectors are data, not code

**Status:** Accepted, 2026-11-13

### Context

Detector logic (challenge-page signatures) will change constantly: new vendors, new variants, tuned regexes. If detectors are Python code, then (a) every future language port re-implements them, (b) community contributors must know Python, (c) rules cannot ship independently of code releases.

### Decision

Every detector is a YAML rule file (format: [interfaces.md Part C](./interfaces.md)) interpreted by the core engine. Canonical rules live in repo-root `rules/`, are packaged with the wheel, and are shared verbatim by every current and future implementation (Python core, Rust core, Go server, WASM playground). Adding a detector = adding a data file.

### Consequences

- Community PRs for new detectors need zero language knowledge; review is diffing signatures.
- The rule format becomes a de-facto public contract; format changes are versioned like the Event contract.
- Detection power is bounded by the matcher primitives; anything not expressible in YAML requires an engine change (accepted — the primitive set is small and generic).

---

## ADR-4: Contract-first — Event/Verdict defined once, validated everywhere

**Status:** Accepted, 2026-11-13

### Context

Multi-language drift is the classic failure of polyglot SDK ecosystems: the TS SDK quietly diverges from the Python one, and the server accepts what neither sends. Scrapewatch plans additional languages post-v0.1 (ADR-1) and must not pay that tax.

### Decision

The `Event` and `Verdict` structures (field tables in [interfaces.md Part A](./interfaces.md)) are the contract, maintained as a JSON Schema alongside the docs. Python dataclasses are generated-from/validated-against it; CI validates fixtures and storage round-trips against the same schema; every future SDK and the future server bind to the same schema file. Additive changes don't bump the version; breaking changes require an ADR.

### Consequences

- SDK parity is enforced mechanically, not by discipline.
- Contract design errors are caught before there are three implementations to fix.
- Slight rigidity: adding a field now carries a schema-change ritual — deliberately cheap (edit schema + doc table), but not free.

---

## ADR-5: Intercept at transport level, not per-framework

**Status:** Accepted, 2026-11-13

### Context

Possible integration strategies: official plugins for every framework (Scrapy middlewares, Firecrawl wrappers, Crawlee hooks, agent callbacks) — N integrations to build and maintain; or interception at the layers everything funnels through.

### Context detail

Practically all Python scraping funnels through three chokepoints: the HTTP client (`requests`/`httpx`), the browser engine (Playwright/CDP — which browser agents themselves sit on), or the user's own loop (explicit API).

### Decision

v0.1 integrates at three levels only (L1: `requests`/`httpx`; L2: Playwright; L3: explicit `job()` API — see [ARCHITECTURE.md §5](../ARCHITECTURE.md)). Framework adapters (L4) are future thin plugins, added per-demand.

### Consequences

- Three integrations cover nearly all Python scrapers, including agent frameworks, without Scrapewatch tracking their release cycles.
- Framework-specific metadata (e.g. Scrapy item pipelines) is unavailable until an adapter exists; acceptable, since Events already carry user-supplied `items`.
- Interceptors must be defensive against client version drift (lazy imports, capability checks) — cost accepted in [components/interceptors.md](../components/interceptors.md).

---

## ADR-6: Fire-and-forget — observability must never break the scraper

**Status:** Accepted, 2026-11-13

### Context

Scrapewatch sits inside the user's revenue-critical pipeline. A monitoring bug that raises, blocks, or leaks memory is worse than the disease it diagnoses; one bad release would destroy trust permanently.

### Decision

Interception is asynchronous and bounded: capture enqueues to a bounded queue (default 10,000 events) and returns in microseconds; a background analyzer thread does all engine/storage/alert work. Every Scrapewatch frame catches its own exceptions, increments self-diagnostic counters (`dropped_events`, `analyzer_errors`), and logs at WARNING or below. No exception ever propagates into user code; on overflow, oldest events are dropped, never the newest.

### Consequences

- User pipelines are structurally immune to Scrapewatch bugs; the never-raise guarantee is testable (fault-injection tests in Phase 2).
- Diagnostics can lag or silently drop under overload — mitigated by surfacing self-diagnostic counters in `scrapewatch report` so degradation itself is observable.
- Some failure modes (e.g. lost events) are accepted as the price of the guarantee.

---

## ADR-7: Apache-2.0 for the library; FSL planned for the future server

**Status:** Accepted, 2026-11-13

### Context

Monetization strategy is open-core (hosted dashboards/alerting later), à la Sentry. License choice trades adoption (permissive) against protection from hosted competitors (copyleft/source-available). AGPL for the library would alienate corporate users with internal AGPL bans, and the library alone hosts no monetizable surface.

### Decision

The Python library (core, interceptors, storage, CLI, and all YAML rules) is Apache-2.0 — permanently. The future sidecar server/dashboard — the monetizable hosted component — will live in a separate repository licensed under FSL (Functional Source License), converting to Apache-2.0 after its change window. Different licenses never mix in one repository or one distribution artifact.

### Consequences

- Zero legal friction for adopting the library, including inside companies that ban copyleft — maximizes the network the project needs.
- Hosted-competitor protection applies exactly where the business value is (server), not where it isn't (library).
- Rules ship under Apache-2.0 with the library: competitors can reuse signatures, accepted — the moat is the engine, corpus, and server, not the regexes.
- The Apache-2.0 promise for the library is permanent; no future relicensing of contributed library code will ever be needed.
