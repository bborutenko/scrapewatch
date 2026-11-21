"""Unit tests for Playwright interceptor.

Note: These tests use mock objects because Playwright requires browser binaries.
Integration tests with real browsers should be in tests/integration/.
"""

from unittest.mock import MagicMock

import pytest

from scrapewatch.core.analyzer import AsyncAnalyzer
from scrapewatch.core.engine import Engine
from scrapewatch.core.rules import load_rules
from scrapewatch.interceptors.playwright_interceptor import (
    WatchedAsyncBrowser,
    WatchedAsyncBrowserContext,
    WatchedSyncBrowser,
    WatchedSyncBrowserContext,
    wrap,
)


class MockBrowser:
    """Mock sync Browser for testing."""
    __module__ = "playwright.sync_api"
    __qualname__ = "Browser"

    def __init__(self):
        self._closed = False

    def new_context(self, **kwargs):
        return MockBrowserContext()

    def new_page(self, **kwargs):
        return MagicMock()

    def close(self):
        self._closed = True

    def is_connected(self):
        return not self._closed


class MockAsyncBrowser:
    """Mock async Browser for testing."""
    __module__ = "playwright.async_api"
    __qualname__ = "Browser"

    def __init__(self):
        self._closed = False

    async def new_context(self, **kwargs):
        return MockAsyncBrowserContext()

    async def new_page(self, **kwargs):
        return MagicMock()

    async def close(self):
        self._closed = True

    def is_connected(self):
        return not self._closed


class MockBrowserContext:
    """Mock sync BrowserContext for testing."""
    __module__ = "playwright.sync_api"
    __qualname__ = "BrowserContext"

    def __init__(self):
        self._listeners = {}

    def on(self, event, handler):
        if event not in self._listeners:
            self._listeners[event] = []
        self._listeners[event].append(handler)

    def new_page(self):
        return MagicMock()


class MockAsyncBrowserContext:
    """Mock async BrowserContext for testing."""
    __module__ = "playwright.async_api"
    __qualname__ = "BrowserContext"

    def __init__(self):
        self._listeners = {}

    def on(self, event, handler):
        if event not in self._listeners:
            self._listeners[event] = []
        self._listeners[event].append(handler)

    async def new_page(self):
        return MagicMock()


def _create_analyzer_and_engine():
    """Helper to create analyzer and engine for tests."""
    engine = Engine(rules=load_rules())
    analyzer = AsyncAnalyzer(engine=engine)
    return analyzer, engine


class TestPlaywrightWrap:
    """Tests for Playwright Browser wrapping."""

    def test_wrap_sync_browser(self):
        """wrap() returns WatchedSyncBrowser for sync Browser."""
        browser = MockBrowser()
        analyzer, engine = _create_analyzer_and_engine()
        wrapped = wrap(browser, job="test", analyzer=analyzer, engine=engine)

        assert isinstance(wrapped, WatchedSyncBrowser)
        assert wrapped._scrapewatch_wrapped is True

    def test_wrap_async_browser(self):
        """wrap() returns WatchedAsyncBrowser for async Browser."""
        browser = MockAsyncBrowser()
        analyzer, engine = _create_analyzer_and_engine()
        wrapped = wrap(browser, job="test", analyzer=analyzer, engine=engine)

        assert isinstance(wrapped, WatchedAsyncBrowser)
        assert wrapped._scrapewatch_wrapped is True

    def test_wrap_sync_context(self):
        """wrap() returns WatchedSyncBrowserContext for sync BrowserContext."""
        context = MockBrowserContext()
        analyzer, engine = _create_analyzer_and_engine()
        wrapped = wrap(context, job="test", analyzer=analyzer, engine=engine)

        assert isinstance(wrapped, WatchedSyncBrowserContext)
        assert wrapped._scrapewatch_wrapped is True

    def test_wrap_async_context(self):
        """wrap() returns WatchedAsyncBrowserContext for async BrowserContext."""
        context = MockAsyncBrowserContext()
        analyzer, engine = _create_analyzer_and_engine()
        wrapped = wrap(context, job="test", analyzer=analyzer, engine=engine)

        assert isinstance(wrapped, WatchedAsyncBrowserContext)
        assert wrapped._scrapewatch_wrapped is True

    def test_each_wrap_gets_its_own_run_id(self):
        """Each wrapped browser gets a unique run_id."""
        browser1 = MockBrowser()
        browser2 = MockBrowser()
        analyzer, engine = _create_analyzer_and_engine()

        wrapped1 = wrap(browser1, job="test", analyzer=analyzer, engine=engine)
        wrapped2 = wrap(browser2, job="test", analyzer=analyzer, engine=engine)

        # Create contexts to get the run_id
        ctx1 = wrapped1.new_context()
        ctx2 = wrapped2.new_context()

        assert ctx1._scrapewatch_jobref.run_id != ctx2._scrapewatch_jobref.run_id

    def test_new_context_returns_watched_context(self):
        """Browser.new_context() returns a watched context."""
        browser = MockBrowser()
        analyzer, engine = _create_analyzer_and_engine()
        wrapped = wrap(browser, job="test", analyzer=analyzer, engine=engine)

        context = wrapped.new_context()
        assert isinstance(context, WatchedSyncBrowserContext)

    def test_context_sets_up_listeners(self):
        """Wrapped context sets up response listeners."""
        context = MockBrowserContext()
        analyzer, engine = _create_analyzer_and_engine()
        wrapped = wrap(context, job="test", analyzer=analyzer, engine=engine)

        # Check that listeners were registered
        assert "response" in wrapped._context._listeners
        assert "request" in wrapped._context._listeners
        assert "requestfailed" in wrapped._context._listeners

    def test_double_wrap_browser_returns_same_object(self):
        """Double wrapping a browser returns the same object."""
        browser = MockBrowser()
        analyzer, engine = _create_analyzer_and_engine()
        wrapped = wrap(browser, job="test", analyzer=analyzer, engine=engine)

        # For wrapped browsers, check marker
        assert wrapped._scrapewatch_wrapped is True

    def test_browser_proxy_methods(self):
        """WatchedBrowser proxies methods to wrapped browser."""
        browser = MockBrowser()
        analyzer, engine = _create_analyzer_and_engine()
        wrapped = wrap(browser, job="test", analyzer=analyzer, engine=engine)

        # Should proxy is_connected
        assert wrapped.is_connected() is True

        # Should proxy close
        wrapped.close()
        assert browser._closed is True

    def test_invalid_client_type_raises(self):
        """wrap() raises TypeError for invalid client types."""
        analyzer, engine = _create_analyzer_and_engine()
        with pytest.raises(TypeError):
            wrap(object(), job="test", analyzer=analyzer, engine=engine)

    def test_analyzer_and_engine_are_set(self):
        """Wrapped browser has analyzer and engine set."""
        browser = MockBrowser()
        analyzer, engine = _create_analyzer_and_engine()
        wrapped = wrap(browser, job="test", analyzer=analyzer, engine=engine)

        assert wrapped._scrapewatch_analyzer is analyzer
        assert wrapped._scrapewatch_engine is engine
