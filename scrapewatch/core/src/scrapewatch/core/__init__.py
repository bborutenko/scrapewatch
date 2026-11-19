"""The pure core: Event -> Verdict, plus rule loading (ADR-2).

Importing this package touches nothing but the stdlib and the YAML
parser: no network, no disk on the evaluation path, no threads, no
framework imports. The one entry point is ``Engine.observe``.
"""

from .engine import Engine
from .event import BODY_SAMPLE_LIMIT, SCHEMA_VERSION, Event, JobRef
from .rules import (
    CompiledGroup,
    CompiledMatch,
    CompiledPrimitive,
    CompiledRule,
    RuleLoadError,
    load_rule_file,
    load_rules,
    packaged_rule_files,
)
from .verdict import PRECEDENCE, Severity, Status, Verdict, aggregate

__all__ = [
    "BODY_SAMPLE_LIMIT",
    "CompiledGroup",
    "CompiledMatch",
    "CompiledPrimitive",
    "CompiledRule",
    "Engine",
    "Event",
    "JobRef",
    "PRECEDENCE",
    "RuleLoadError",
    "SCHEMA_VERSION",
    "Severity",
    "Status",
    "Verdict",
    "aggregate",
    "load_rule_file",
    "load_rules",
    "packaged_rule_files",
]
