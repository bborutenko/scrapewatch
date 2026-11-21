"""Unit tests for httpx interceptor."""

import httpx
import pytest

import scrapewatch as sw
from scrapewatch.core.analyzer import AsyncAnalyzer
from scrapewatch.core.engine import Engine
from scrapewatch.core.rules import load_rules
from scrapewatch.interceptors.httpx_interceptor import WatchedClient, WatchedAsyncClient


class TestHttpxWrap:
    """Tests for httpx.Client wrapping."""

    def test_wrap_returns_a_new_equivalent_client(self):
        """wrap() returns a WatchedClient with same behavior."""
        client = httpx.Client(headers={"X-Test": "1"}, cookies={"session": "abc"})
        wrapped = sw.watch(client, job="test")

        assert isinstance(wrapped, WatchedClient)
        assert wrapped.headers.get("X-Test") == "1"
        assert wrapped.cookies.get("session") == "abc"

    def test_cookies_survive_the_wrap(self):
        """Cookies are preserved after wrapping."""
        client = httpx.Client(cookies={"user": "123", "session": "xyz"})
        wrapped = sw.watch(client, job="test")

        assert wrapped.cookies.get("user") == "123"
        assert wrapped.cookies.get("session") == "xyz"

    def test_double_wrap_returns_same_object(self):
        """Double wrapping returns the already-wrapped client."""
        client = httpx.Client()
        wrapped = sw.watch(client, job="test1")

        # Second wrap should return the same object
        double = sw.watch(wrapped, job="test2")
        assert double is wrapped

    def test_scrapewatch_wrapped_marker_is_set(self):
        """Wrapped client has _scrapewatch_wrapped marker."""
        client = httpx.Client()
        wrapped = sw.watch(client, job="test")

        assert hasattr(wrapped, "_scrapewatch_wrapped")
        assert wrapped._scrapewatch_wrapped is True

    def test_each_wrap_gets_its_own_run_id(self):
        """Each wrapped client gets a unique run_id."""
        client1 = httpx.Client()
        client2 = httpx.Client()

        wrapped1 = sw.watch(client1, job="test")
        wrapped2 = sw.watch(client2, job="test")

        assert wrapped1._scrapewatch_jobref.run_id != wrapped2._scrapewatch_jobref.run_id

    def test_analyzer_and_engine_are_set(self):
        """Wrapped client has analyzer and engine set."""
        client = httpx.Client()
        wrapped = sw.watch(client, job="test")

        assert wrapped._scrapewatch_analyzer is not None
        assert wrapped._scrapewatch_engine is not None
        assert isinstance(wrapped._scrapewatch_analyzer, AsyncAnalyzer)
        assert isinstance(wrapped._scrapewatch_engine, Engine)

    def test_custom_rules_create_separate_engine(self):
        """Custom rules create a separate engine with those rules."""
        import tempfile
        import yaml

        # Create a temp rule file
        rule = {
            "id": "test-rule",
            "name": "Test Rule",
            "verdict": "blocked",
            "severity": "high",
            "match": {"any_of": [{"body_re": ["test-pattern-xyz"]}]},
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump([rule], f)
            rule_path = f.name

        try:
            client = httpx.Client()
            wrapped = sw.watch(client, job="test", rules=[rule_path])

            # Should have an engine with the custom rule
            # Check that the rule is loaded by checking the engine's rules
            rule_ids = [r.id for r in wrapped._scrapewatch_engine._rules]
            assert "test-rule" in rule_ids
        finally:
            import os
            os.unlink(rule_path)

    def test_invalid_custom_rules_fail_loudly_at_wrap_time(self):
        """Invalid rule files raise at wrap time, not mid-scrape."""
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("invalid: yaml: content: [")
            rule_path = f.name

        try:
            client = httpx.Client()
            with pytest.raises(Exception):  # yaml parse error
                sw.watch(client, job="test", rules=[rule_path])
        finally:
            import os
            os.unlink(rule_path)


class TestHttpxAsyncWrap:
    """Tests for httpx.AsyncClient wrapping."""

    def test_wrap_async_client(self):
        """wrap() returns a WatchedAsyncClient for AsyncClient."""
        client = httpx.AsyncClient()
        wrapped = sw.watch(client, job="test")

        assert isinstance(wrapped, WatchedAsyncClient)

    def test_async_double_wrap_returns_same_object(self):
        """Double wrapping async client returns the same object."""
        client = httpx.AsyncClient()
        wrapped = sw.watch(client, job="test1")

        double = sw.watch(wrapped, job="test2")
        assert double is wrapped

    def test_async_scrapewatch_wrapped_marker_is_set(self):
        """Wrapped async client has _scrapewatch_wrapped marker."""
        client = httpx.AsyncClient()
        wrapped = sw.watch(client, job="test")

        assert wrapped._scrapewatch_wrapped is True

    def test_async_analyzer_and_engine_are_set(self):
        """Wrapped async client has analyzer and engine set."""
        client = httpx.AsyncClient()
        wrapped = sw.watch(client, job="test")

        assert wrapped._scrapewatch_analyzer is not None
        assert wrapped._scrapewatch_engine is not None
