"""Engine — the pure core's one entry point: ``observe(event) -> Verdict``.

Everything else in scrapewatch is a shell around this class
(ARCHITECTURE §3, ADR-2): no network, no disk, no threads, no framework
imports on the evaluation path. Pipeline and its cheap-first ordering:
docs/components/core-engine.md §4.

Failure policy: ``observe`` never raises into user code — any failure of
scrapewatch itself degrades to ``Verdict.unknown`` with the reason
recorded, counted in ``Engine.failures`` and logged at WARNING
(ARCHITECTURE §7, ADR-8). Broken *rules* are a different story: they
die loudly at load time (rules.py, C.3.5) and never reach this module.
"""

import dataclasses
import hashlib
import html
import json
import logging
import re
from collections.abc import Callable, Iterable

from .event import Event
from .rules import CompiledGroup, CompiledPrimitive, CompiledRule, load_rules
from .verdict import Severity, Status, Verdict, aggregate

__all__ = ["Engine"]

logger = logging.getLogger("scrapewatch.core.engine")

#: <title> extraction: a regex slice, not a DOM tree — body_sample is
#: capped at 64 KiB by the contract, and malformed HTML must still
#: yield a title (core-engine.md §7, resolved: first slice wins).
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

#: All <script src="..."> values, in document order.
_SCRIPT_SRC_RE = re.compile(r"""<script[^>]+\bsrc\s*=\s*["']([^"']*)["']""", re.IGNORECASE)


@dataclasses.dataclass(frozen=True, slots=True)
class _Hints:
    """Per-event derivations extracted once for all detectors (core-engine.md §3.3)."""

    title: str | None
    script_srcs: tuple[str, ...]


#: One uniform matcher interface: (primitive, event, hints) -> the text
#: of the signature that matched, or None. A new primitive kind is one
#: function plus one row in the Part C table — rules stay data (ADR-3).
type PrimitiveMatcher = Callable[[CompiledPrimitive, Event, _Hints], str | None]


def _match_title_re(primitive: CompiledPrimitive, event: Event, hints: _Hints) -> str | None:
    if hints.title is None:
        return None
    return next((p.pattern for p in primitive.patterns if p.search(hints.title)), None)


def _match_body_re(primitive: CompiledPrimitive, event: Event, hints: _Hints) -> str | None:
    return next((p.pattern for p in primitive.patterns if p.search(event.body_sample)), None)


def _match_script_src_re(primitive: CompiledPrimitive, event: Event, hints: _Hints) -> str | None:
    return next(
        (p.pattern for p in primitive.patterns for src in hints.script_srcs if p.search(src)),
        None,
    )


def _match_header(primitive: CompiledPrimitive, event: Event, hints: _Hints) -> str | None:
    value = event.headers.get(primitive.header_name or "")
    if value is None:
        return None
    return next((p.pattern for p in primitive.patterns if p.search(value)), None)


_PRIMITIVE_MATCHERS: dict[str, PrimitiveMatcher] = {
    "title_re": _match_title_re,
    "body_re": _match_body_re,
    "script_src_re": _match_script_src_re,
    "header": _match_header,
}


class Engine:
    """Evaluates compiled detector rules against Events. Nothing else.

    ``rules`` defaults to the packaged detector set. One Engine is built
    once per ``watch()``/``check()`` call and reused for every event:
    regexes are already compiled, so evaluation allocates nothing heavy.
    """

    def __init__(self, rules: Iterable[CompiledRule] | None = None) -> None:
        self._rules: tuple[CompiledRule, ...] = tuple(rules) if rules is not None else load_rules()
        #: Self-diagnostic counter (ARCHITECTURE §7.4): failed observe() calls.
        self.failures = 0

    def observe(self, event: Event) -> Verdict:
        """Classify one Event — the one public entry point of the core.

        Never raises: scrapewatch's own failure degrades to
        ``Verdict.unknown`` (ADR-8), counted in ``self.failures``.
        """
        event_hash = self._fingerprint(event)
        try:
            return self._classify(event, event_hash)
        except Exception as exc:  # the never-raise boundary (ADR-6, ARCHITECTURE §7.2)
            self.failures += 1
            logger.warning("scrapewatch could not classify %s: %r", event.url, exc)
            return Verdict.unknown(reason=f"analysis failed: {exc!r}", event_hash=event_hash)

    # --- pipeline (core-engine.md §4) -------------------------------------

    def _classify(self, event: Event, event_hash: str) -> Verdict:
        hints = self._extract_hints(event)
        candidates = self._check_detectors(event, hints, event_hash)
        # Phase 3 seam: item-schema validation joins here, producing the
        # same (severity, verdict) candidates with detector_id="schema"
        # (data-quality.md). Until then, items are recorded but not judged.
        if not candidates:
            return Verdict.ok(event_hash=event_hash)
        return aggregate(candidates)

    def _check_detectors(
        self, event: Event, hints: _Hints, event_hash: str
    ) -> list[tuple[Severity, Verdict]]:
        candidates = []
        for rule in self._rules:
            hit = self._match_rule(rule, event, hints, event_hash)
            if hit is not None:
                candidates.append(hit)
        return candidates

    def _match_rule(
        self, rule: CompiledRule, event: Event, hints: _Hints, event_hash: str
    ) -> tuple[Severity, Verdict] | None:
        """One detector against one event; None when it does not fire (C.3)."""
        fired_groups: list[tuple[CompiledGroup, list[tuple[CompiledPrimitive, str]]]] = []

        any_fired = False
        for group in rule.match.any_of:
            hits = self._fire_group(group, event, hints)
            if hits:  # a group inside any_of fires when ANY primitive fires (C.3.2)
                any_fired = True
                fired_groups.append((group, hits))

        all_satisfied = bool(rule.match.all_of)
        for group in rule.match.all_of:
            hits = self._fire_group(group, event, hints)
            if len(hits) == len(group):  # a group inside all_of fires when ALL primitives fire (C.3.2)
                fired_groups.append((group, hits))
            else:
                all_satisfied = False

        if not (any_fired or all_satisfied):  # detector fires when any_of OR all_of is satisfied (C.3.3)
            return None

        matched = sum(len(hits) for _, hits in fired_groups)
        total = sum(len(group) for group, _ in fired_groups)
        return rule.severity, self._build_verdict(rule, event, event_hash, fired_groups, matched, total)

    def _build_verdict(
        self,
        rule: CompiledRule,
        event: Event,
        event_hash: str,
        fired_groups: list[tuple[CompiledGroup, list[tuple[CompiledPrimitive, str]]]],
        matched: int,
        total: int,
    ) -> Verdict:
        confidence = 0.5 + 0.5 * (matched / total)  # C.3.4
        if rule.match.status_hint is not None:
            confidence += 0.1 if event.status_code in rule.match.status_hint else -0.1
        confidence = min(1.0, max(0.0, confidence))

        signatures = [
            f"{primitive.kind}[{primitive.header_name}]: {text}"
            if primitive.header_name
            else f"{primitive.kind}: {text}"
            for _, hits in fired_groups
            for primitive, text in hits
        ]
        return Verdict(
            status=rule.verdict,
            detector_id=rule.id,
            reason=self._reason(rule, event),
            confidence=confidence,
            evidence={
                "matched_signatures": signatures,
                "matched_primitives": matched,
                "total_primitives": total,
            },
            event_hash=event_hash,
        )

    def _fire_group(
        self, group: CompiledGroup, event: Event, hints: _Hints
    ) -> list[tuple[CompiledPrimitive, str]]:
        """Matched (primitive, signature-text) pairs within one group."""
        return [
            (primitive, text)
            for primitive in group
            if (text := _PRIMITIVE_MATCHERS[primitive.kind](primitive, event, hints)) is not None
        ]

    # --- helpers ------------------------------------------------------------

    @staticmethod
    def _reason(rule: CompiledRule, event: Event) -> str:
        """Human one-liner (A.2); the fake-200 gets the phrasing it deserves."""
        if event.status_code == 200:
            return f"{rule.name} behind HTTP 200"  # the failure mode the library exists for
        if event.status_code is None:
            return f"{rule.name} (no response received)"
        return f"{rule.name} (HTTP {event.status_code})"

    @staticmethod
    def _extract_hints(event: Event) -> _Hints:
        title_match = _TITLE_RE.search(event.body_sample)
        title = html.unescape(title_match.group(1)).strip() if title_match else None
        return _Hints(title=title, script_srcs=tuple(_SCRIPT_SRC_RE.findall(event.body_sample)))

    @staticmethod
    def _fingerprint(event: Event) -> str:
        """``event_hash`` per A.2: sha256 of the canonical JSON of the Event
        (sorted keys, compact separators, ``default=str``) — the same event
        always hashes the same, so storage can correlate verdicts with events.
        """
        canonical = json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
