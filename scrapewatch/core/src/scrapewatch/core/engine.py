"""Engine — classifies Events against detector rules.

The pure core of scrapewatch: no network, no disk, no threads, no framework imports.
One entry point: engine.observe(event) -> Verdict.

Never raises into user code — failures return Verdict.unknown().
"""

import hashlib
import html
import json
import re
from collections.abc import Iterable

from .event import Event
from .rules import CompiledGroup, CompiledRule
from .verdict import Severity, Verdict, aggregate

__all__ = ["Engine"]

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_SCRIPT_SRC_RE = re.compile(r"""<script[^>]+\bsrc\s*=\s*["']([^"']*)["']""", re.IGNORECASE)

_MATCHERS = {
    "title_re": lambda p, e, h: next((r.pattern for r in p.patterns if h.title and r.search(h.title)), None),
    "body_re": lambda p, e, h: next((r.pattern for r in p.patterns if e.body_sample and r.search(e.body_sample)), None),
    "script_src_re": lambda p, e, h: next(
        (r.pattern for r in p.patterns for src in h.script_srcs if r.search(src)), None
    ),
    "header": lambda p, e, h: next(
        (r.pattern for r in p.patterns if p.header_name and e.headers.get(p.header_name) and r.search(e.headers.get(p.header_name))), None
    ),
}


class Engine:
    """Evaluates detector rules against Events."""

    def __init__(self, rules: Iterable[CompiledRule]) -> None:
        self._rules = tuple(rules)
        self.failures = 0

    def observe(self, event: Event) -> Verdict:
        """Classify an Event. Never raises."""
        event_hash = self._fingerprint(event)
        try:
            return self._classify(event, event_hash)
        except Exception as exc:
            self.failures += 1
            return Verdict.unknown(reason=f"analysis failed: {exc!r}", event_hash=event_hash)

    def _classify(self, event: Event, event_hash: str) -> Verdict:
        """Run all detectors and return the winning verdict."""
        hints = self._extract_hints(event)
        candidates = []
        for rule in self._rules:
            result = self._match_rule(rule, event, hints, event_hash)
            if result is not None:
                candidates.append(result)

        if not candidates:
            return Verdict.ok(event_hash=event_hash)
        return aggregate(candidates)

    def _match_rule(
        self, rule: CompiledRule, event: Event, hints, event_hash: str
    ) -> tuple[Severity, Verdict] | None:
        """Check if a rule matches the event."""
        fired_groups = []
        any_fired = False

        for group in rule.match.any_of:
            hits = self._match_group(group, event, hints)
            if hits:
                any_fired = True
                fired_groups.append((group, hits))

        all_satisfied = bool(rule.match.all_of)
        for group in rule.match.all_of:
            hits = self._match_group(group, event, hints)
            if len(hits) == len(group):
                fired_groups.append((group, hits))
            else:
                all_satisfied = False

        if not (any_fired or all_satisfied):
            return None

        matched = sum(len(hits) for _, hits in fired_groups)
        total = sum(len(group) for group, _ in fired_groups)
        return rule.severity, self._build_verdict(rule, event, event_hash, fired_groups, matched, total)

    def _match_group(self, group: CompiledGroup, event: Event, hints) -> list:
        """Match all primitives in a group."""
        return [
            (primitive, text)
            for primitive in group
            if (text := _MATCHERS[primitive.kind](primitive, event, hints)) is not None
        ]

    def _build_verdict(self, rule, event, event_hash, fired_groups, matched, total) -> Verdict:
        """Build a verdict from matched rule."""
        confidence = 0.5 + 0.5 * (matched / total)
        if rule.match.status_hint:
            confidence += 0.1 if event.status_code in rule.match.status_hint else -0.1
        confidence = min(1.0, max(0.0, confidence))

        signatures = [
            f"{primitive.kind}[{primitive.header_name}]: {text}" if primitive.header_name else f"{primitive.kind}: {text}"
            for group, hits in fired_groups
            for primitive, text in hits
        ]

        return Verdict(
            status=rule.verdict,
            detector_id=rule.id,
            reason=self._build_reason(rule, event),
            confidence=confidence,
            evidence={
                "matched_signatures": signatures,
                "matched_primitives": matched,
                "total_primitives": total,
            },
            event_hash=event_hash,
        )

    @staticmethod
    def _build_reason(rule: CompiledRule, event: Event) -> str:
        """Human-readable reason for the verdict."""
        if event.status_code == 200:
            return f"{rule.name} behind HTTP 200"
        if event.status_code is None:
            return f"{rule.name} (no response received)"
        return f"{rule.name} (HTTP {event.status_code})"

    @staticmethod
    def _extract_hints(event: Event):
        """Extract title and script_srcs from HTML body."""
        title_match = _TITLE_RE.search(event.body_sample)
        title = html.unescape(title_match.group(1)).strip() if title_match else None
        script_srcs = tuple(_SCRIPT_SRC_RE.findall(event.body_sample))

        class Hints:
            __slots__ = ("title", "script_srcs")
            def __init__(self, title, script_srcs):
                self.title = title
                self.script_srcs = script_srcs

        return Hints(title, script_srcs)

    @staticmethod
    def _fingerprint(event: Event) -> str:
        """SHA-256 hash of event's canonical JSON."""
        canonical = json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
