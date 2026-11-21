"""Rule loading/compilation: Part C contract, loud failures, override by id."""

import re

import pytest

from scrapewatch.core.rules import RuleLoadError, load_rule_file, load_rules
from scrapewatch.core.verdict import Severity, Status

VALID = r"""
id: test-detector
name: Test detector
verdict: blocked
severity: high
reference: https://example.com/docs
match:
  status_hint: [403, 503]
  any_of:
    - title_re:
        - "Just a moment"
    - body_re:
        - "challenge-platform"
      script_src_re:
        - 'challenges\.example\.com'
"""


def _write(tmp_path, text, name="rule.yaml"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_valid_file_compiles_every_field(tmp_path):
    (rule,) = load_rule_file(_write(tmp_path, VALID))

    assert rule.id == "test-detector"
    assert rule.name == "Test detector"
    assert rule.verdict is Status.BLOCKED
    assert rule.severity is Severity.HIGH
    assert rule.reference == "https://example.com/docs"
    assert rule.match.status_hint == (403, 503)
    assert len(rule.match.any_of) == 2
    assert rule.match.all_of == ()


def test_regexes_are_precompiled_and_grouped_deterministically(tmp_path):
    (rule,) = load_rule_file(_write(tmp_path, VALID))
    title_group, mixed_group = rule.match.any_of

    assert [p.kind for p in title_group] == ["title_re"]
    # second group holds both primitives, compiled in sorted-key order
    assert [p.kind for p in mixed_group] == ["body_re", "script_src_re"]
    assert all(isinstance(p.patterns[0], re.Pattern) for p in (*title_group, *mixed_group))


def test_title_re_is_case_insensitive_only(tmp_path):
    (rule,) = load_rule_file(_write(tmp_path, VALID))
    title_group, mixed_group = rule.match.any_of

    assert title_group[0].patterns[0].flags & re.IGNORECASE
    assert not mixed_group[0].patterns[0].flags & re.IGNORECASE  # body_re stays sensitive


def test_list_and_multidoc_files_yield_every_detector(tmp_path):
    two_docs = VALID + "\n---\n" + VALID.replace("test-detector", "second-detector")
    rules = load_rule_file(_write(tmp_path, two_docs))
    assert [r.id for r in rules] == ["test-detector", "second-detector"]


def test_missing_required_field_is_named(tmp_path):
    broken = VALID.replace("name: Test detector\n", "")
    with pytest.raises(RuleLoadError, match="name"):
        load_rule_file(_write(tmp_path, broken))


def test_unknown_top_level_field_is_rejected(tmp_path):
    with pytest.raises(RuleLoadError, match="unknown top-level"):
        load_rule_file(_write(tmp_path, VALID + "extras: 1\n"))


def test_verdict_is_limited_to_blocked_and_garbage(tmp_path):
    with pytest.raises(RuleLoadError, match="blocked, garbage"):
        load_rule_file(_write(tmp_path, VALID.replace("verdict: blocked", "verdict: ok")))


def test_invalid_severity_is_rejected(tmp_path):
    with pytest.raises(RuleLoadError, match="severity"):
        load_rule_file(_write(tmp_path, VALID.replace("severity: high", "severity: critical")))


def test_invalid_regex_fails_loudly_naming_file_and_pattern(tmp_path):
    broken = VALID.replace('"challenge-platform"', '"("')
    with pytest.raises(RuleLoadError, match=re.escape("rule.yaml")) as excinfo:
        load_rule_file(_write(tmp_path, broken))
    assert "'('" in str(excinfo.value)


def test_unknown_primitive_is_rejected(tmp_path):
    broken = VALID.replace("title_re:", "onclick_re:")
    with pytest.raises(RuleLoadError, match="onclick_re"):
        load_rule_file(_write(tmp_path, broken))


def test_empty_group_is_rejected(tmp_path):
    broken = VALID.replace("- title_re:\n        - \"Just a moment\"", "- {}")
    with pytest.raises(RuleLoadError, match="non-empty"):
        load_rule_file(_write(tmp_path, broken))


def test_match_without_any_logic_is_rejected(tmp_path):
    broken = VALID.split("match:")[0] + "match:\n  status_hint: [403]\n"
    with pytest.raises(RuleLoadError, match="any_of / all_of"):
        load_rule_file(_write(tmp_path, broken))


def test_status_hint_must_be_ints(tmp_path):
    with pytest.raises(RuleLoadError, match="status_hint"):
        load_rule_file(_write(tmp_path, VALID.replace("[403, 503]", '["403"]')))


def test_comment_only_file_has_no_detectors(tmp_path):
    with pytest.raises(RuleLoadError, match="no detectors"):
        load_rule_file(_write(tmp_path, "# nothing to see here\n"))


def test_header_names_are_lowercased(tmp_path):
    rule_text = r"""
id: header-check
name: Header check
verdict: garbage
severity: low
match:
  all_of:
    - header:
        Server: '^cloudflare$'
"""
    (rule,) = load_rule_file(_write(tmp_path, rule_text))
    (primitive,) = rule.match.all_of[0]
    assert primitive.kind == "header"
    assert primitive.header_name == "server"


def test_load_rules_without_paths_returns_empty():
    assert load_rules() == ()


def test_user_rule_override_by_id(tmp_path):
    first = VALID.replace("test-detector", "rule-1")
    second = VALID.replace("test-detector", "rule-1").replace(
        "name: Test detector", "name: Override"
    )
    rules = load_rules([_write(tmp_path, first), _write(tmp_path, second, "second.yaml")])

    by_id = {rule.id: rule for rule in rules}
    assert len(rules) == len(by_id)
    assert by_id["rule-1"].name == "Override"


def test_missing_file_is_a_loud_error(tmp_path):
    with pytest.raises(RuleLoadError, match="cannot read"):
        load_rule_file(tmp_path / "absent.yaml")
