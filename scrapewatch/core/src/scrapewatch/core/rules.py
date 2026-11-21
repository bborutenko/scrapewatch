"""Rule loading and compilation: YAML detector files -> CompiledRule set.

Format source of truth: docs/contracts/interfaces.md Part C.

Detectors are data, not code (ADR-3) — this module is the only place
that knows the YAML shape; the engine consumes CompiledRule objects.

Rules are optional — if no rules are provided, the engine returns
ok verdicts for all events. Users can pass custom rule files via
watch(..., rules=[...]).
"""

import dataclasses
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TypeAlias

import yaml

from ..config import get_logger
from .verdict import Severity, Status

logger = get_logger()

__all__ = [
    "CompiledMatch",
    "CompiledPrimitive",
    "CompiledRule",
    "RuleLoadError",
    "load_rule_file",
    "load_rules",
]


class RuleLoadError(ValueError):
    """A rule file violates the Part C contract; the message names file and cause."""


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class CompiledPrimitive:
    """One matching primitive (C.2): a kind plus its pre-compiled regexes.

    ``header_name`` is set only for ``kind == "header"`` and is already
    lowercased — Event.headers keys are lowercase by contract (A.1).
    """

    kind: str  # title_re | body_re | script_src_re | header
    patterns: tuple[re.Pattern[str], ...]
    header_name: str | None = None


#: A matcher group: primitives combined per C.3.2. Whether the group
#: needs ANY or ALL of them depends on the parent list (any_of / all_of)
#: — that firing logic lives in the engine, not in the data.
CompiledGroup: TypeAlias = tuple[CompiledPrimitive, ...]


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class CompiledMatch:
    """The ``match`` block with every regex compiled once (C.3.5)."""

    status_hint: tuple[int, ...] | None = None  # adjusts confidence ±0.1, never sufficient alone
    any_of: tuple[CompiledGroup, ...] = ()  # detector fires if ANY of these groups fires
    all_of: tuple[CompiledGroup, ...] = ()  # ... or if ALL of these groups fire (C.3.3)


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class CompiledRule:
    """One detector; fields in C.2 table order."""

    id: str  # stable identifier; doubles as the fixtures directory name
    name: str  # human-readable label used in reasons and reports
    verdict: Status  # classification when the detector fires — blocked or garbage only
    severity: Severity  # resolves multi-match conflicts (A.2)
    match: CompiledMatch
    reference: str | None = None  # documentation link for the protection/pattern


_TOP_LEVEL_KEYS = frozenset({"id", "name", "verdict", "severity", "reference", "match"})
_REQUIRED_KEYS = frozenset({"id", "name", "verdict", "severity", "match"})
_MATCH_KEYS = frozenset({"status_hint", "any_of", "all_of"})
_REGEX_PRIMITIVES = frozenset({"title_re", "body_re", "script_src_re"})
_GROUP_KEYS = _REGEX_PRIMITIVES | {"header"}
_VERDICTS = {"blocked": Status.BLOCKED, "garbage": Status.GARBAGE}  # C.2: only these two
_SEVERITIES = {"low": Severity.LOW, "medium": Severity.MEDIUM, "high": Severity.HIGH}


def load_rules(extra_paths: Sequence = ()) -> tuple[CompiledRule, ...]:
    """Load rules from configured rules_dir and user-provided files.
    
    Rules are optional — if no rules are loaded, returns an empty tuple.
    The engine will return ok verdicts for all events when no rules are loaded.
    
    Loads from:
    1. rules_dir if configured via sw.configure(rules_dir="...")
    2. extra_paths if provided
    
    Args:
        extra_paths: Optional list of YAML rule file paths
    
    Returns:
        Tuple of compiled rules, deduplicated by id (last wins)
    
    Raises:
        RuleLoadError: If extra_paths contains invalid rule files
    """
    from ..config import get_settings
    
    by_id: dict[str, CompiledRule] = {}
    
    settings = get_settings()
    
    # Load from rules_dir if configured (errors are warnings)
    if settings.rules_dir:
        rules_path = Path(settings.rules_dir)
        if rules_path.is_dir():
            for rule_file in sorted(rules_path.glob("*.yaml")):
                try:
                    for rule in load_rule_file(rule_file):
                        by_id[rule.id] = rule
                except RuleLoadError as exc:
                    logger.warning(f"failed to load {rule_file}: {exc}")
    
    # Load from extra_paths (errors are raised)
    for path in extra_paths:
        for rule in load_rule_file(Path(path)):
            by_id[rule.id] = rule
    
    total_sources = (1 if settings.rules_dir else 0) + len(extra_paths)
    
    if not by_id and total_sources > 0:
        logger.warning("rules provided but none loaded successfully")
    elif not by_id:
        logger.warning("no rules loaded — all events will be classified as ok")
    else:
        logger.info(f"loaded {len(by_id)} rules from {total_sources} sources")
    
    return tuple(by_id.values())


def load_rule_file(path: Any) -> tuple[CompiledRule, ...]:
    """All detectors in one YAML file: a mapping, a list of mappings, or multi-doc."""
    origin = getattr(path, "name", str(path))

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuleLoadError(f"{origin}: cannot read rule file: {exc}") from exc

    try:
        documents = list(yaml.safe_load_all(text))
    except yaml.YAMLError as exc:
        raise RuleLoadError(f"{origin}: invalid YAML: {exc}") from exc

    rules: list[CompiledRule] = []
    for document in documents:
        if document is None:
            continue  # empty doc (trailing `---`, comment-only chunk)
        entries = document if isinstance(document, list) else [document]
        for entry in entries:
            if not isinstance(entry, dict):
                kind = type(entry).__name__
                raise RuleLoadError(f"{origin}: a detector must be a mapping, got {kind}")
            rules.append(_compile(entry, origin))

    if not rules:
        raise RuleLoadError(f"{origin}: no detectors found")
    return tuple(rules)


def _compile(doc: dict[str, Any], origin: str) -> CompiledRule:
    unknown = set(doc) - _TOP_LEVEL_KEYS
    if unknown:
        raise RuleLoadError(f"{origin}: unknown top-level field(s): {', '.join(sorted(map(str, unknown)))}")

    missing = _REQUIRED_KEYS - set(doc)
    if missing:
        raise RuleLoadError(f"{origin}: missing required field(s): {', '.join(sorted(missing))}")

    if not isinstance(doc["verdict"], str) or doc["verdict"] not in _VERDICTS:
        allowed = ", ".join(sorted(_VERDICTS))
        raise RuleLoadError(f"{origin}: verdict must be one of: {allowed} (C.2)")

    if not isinstance(doc["severity"], str) or doc["severity"] not in _SEVERITIES:
        allowed = ", ".join(sorted(_SEVERITIES))
        raise RuleLoadError(f"{origin}: severity must be one of: {allowed}")

    reference = doc.get("reference")
    if reference is not None and not isinstance(reference, str):
        raise RuleLoadError(f"{origin}: reference must be a URL string")

    return CompiledRule(
        id=_non_empty_str(doc["id"], "id", origin),
        name=_non_empty_str(doc["name"], "name", origin),
        verdict=_VERDICTS[doc["verdict"]],
        severity=_SEVERITIES[doc["severity"]],
        match=_compile_match(doc["match"], origin),
        reference=reference,
    )


def _non_empty_str(value: Any, key: str, origin: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuleLoadError(f"{origin}: {key} must be a non-empty string")
    return value


def _compile_match(raw: Any, origin: str) -> CompiledMatch:
    if not isinstance(raw, dict):
        raise RuleLoadError(f"{origin}: match must be a mapping")

    unknown = set(raw) - _MATCH_KEYS
    if unknown:
        raise RuleLoadError(f"{origin}: unknown match field(s): {', '.join(sorted(map(str, unknown)))}")

    status_hint = None
    if "status_hint" in raw:
        hint = raw["status_hint"]
        ints_ok = isinstance(hint, list) and hint and all(type(item) is int for item in hint)
        if not ints_ok:
            raise RuleLoadError(f"{origin}: status_hint must be a non-empty list of ints")
        status_hint = tuple(hint)

    any_of = _compile_groups(raw.get("any_of"), "any_of", origin)
    all_of = _compile_groups(raw.get("all_of"), "all_of", origin)

    if not any_of and not all_of:
        raise RuleLoadError(
            f"{origin}: match needs at least one of any_of / all_of — "
            "a detector that can never fire is broken data, not a disabled rule (C.3.5)"
        )
    return CompiledMatch(status_hint=status_hint, any_of=any_of, all_of=all_of)


def _compile_groups(raw: Any, list_name: str, origin: str) -> tuple[CompiledGroup, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not raw:
        raise RuleLoadError(f"{origin}: {list_name} must be a non-empty list of groups")
    return tuple(_compile_group(entry, list_name, index, origin) for index, entry in enumerate(raw))


def _compile_group(raw: Any, list_name: str, index: int, origin: str) -> CompiledGroup:
    where = f"{origin}: {list_name}[{index}]"
    if not isinstance(raw, dict) or not raw:
        raise RuleLoadError(f"{where}: a group must be a non-empty mapping of primitives")

    unknown = set(raw) - _GROUP_KEYS
    if unknown:
        raise RuleLoadError(f"{where}: unknown primitive(s): {', '.join(sorted(map(str, unknown)))}")

    primitives: list[CompiledPrimitive] = []
    for kind in sorted(raw):  # sorted: identical files compile to identical rules
        if kind == "header":
            primitives.extend(_compile_header(raw[kind], where))
        else:
            primitives.append(_compile_regex_primitive(kind, raw[kind], where))
    return tuple(primitives)


def _compile_regex_primitive(kind: str, value: Any, where: str) -> CompiledPrimitive:
    if not isinstance(value, list) or not value or not all(isinstance(p, str) for p in value):
        raise RuleLoadError(f"{where}: {kind} must be a non-empty list of regex strings")
    flags = re.IGNORECASE if kind == "title_re" else 0  # C.2: title matching is case-insensitive
    return CompiledPrimitive(kind=kind, patterns=_compile_patterns(value, flags, where))


def _compile_header(value: Any, where: str) -> list[CompiledPrimitive]:
    pairs_ok = (
        isinstance(value, dict)
        and value
        and all(isinstance(k, str) and isinstance(v, str) for k, v in value.items())
    )
    if not pairs_ok:
        raise RuleLoadError(f"{where}: header must be a non-empty {{name: value_re}} mapping of strings")
    return [
        CompiledPrimitive(
            kind="header",
            patterns=_compile_patterns([value_re], 0, where),
            header_name=name.lower(),
        )
        for name, value_re in value.items()
    ]


def _compile_patterns(patterns: list[str], flags: int, where: str) -> tuple[re.Pattern[str], ...]:
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern, flags))
        except re.error as exc:
            # C.3.5: fail loudly, naming file and pattern — never silently disable
            raise RuleLoadError(f"{where}: invalid regex {pattern!r}: {exc}") from exc
    return tuple(compiled)
