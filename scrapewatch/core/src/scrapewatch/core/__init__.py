"""The pure core: Event -> Verdict, plus rule loading (ADR-2).

Importing this package touches nothing but the stdlib and the YAML
parser: no network, no disk on the evaluation path, no threads, no
framework imports. The one entry point is ``Engine.observe``.
"""

from .engine import Engine, EngineProtocol
from .event import SCHEMA_VERSION, Event, JobRef
from .exceptions import SwBlocked, SwGarbage
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
    "CompiledGroup",
    "CompiledMatch",
    "CompiledPrimitive",
    "CompiledRule",
    "Engine",
    "EngineProtocol",
    "Event",
    "JobRef",
    "PRECEDENCE",
    "RuleLoadError",
    "SCHEMA_VERSION",
    "Severity",
    "Status",
    "SwBlocked",
    "SwGarbage",
    "Verdict",
    "aggregate",
    "load_rule_file",
    "load_rules",
    "packaged_rule_files",
]
