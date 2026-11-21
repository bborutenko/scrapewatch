"""Playwright interceptors integration tests.

Note: These tests require Playwright browsers to be installed.
Run `playwright install` before running these tests.
If browsers are not installed, tests will be skipped.
"""

import subprocess

import pytest

import scrapewatch as sw


def playwright_browsers_installed() -> bool:
    """Check if Playwright browsers are installed."""
    try:
        result = subprocess.run(
            ["python", "-m", "playwright", "install", "--dry-run", "chromium"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # If browsers are installed, dry-run should succeed
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


# Skip all tests in this module if Playwright browsers are not installed
pytestmark = pytest.mark.skipif(
    not playwright_browsers_installed(),
    reason="Playwright browsers not installed. Run 'playwright install'",
)


class TestPlaywrightSyncLive:
    """Tests for Playwright sync Browser with real browser.

    These tests actually launch a browser and navigate to pages.
    They verify that interceptors capture response events.
    """

    def test_browser_wrap_creates_watched_browser(self):
        """Wrapping a Browser returns WatchedSyncBrowser."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                watched = sw.watch(browser, job="test-playwright")

                assert hasattr(watched, "_scrapewatch_wrapped")
                assert watched._scrapewatch_wrapped is True
            finally:
                browser.close()

    def test_new_context_returns_watched_context(self):
        """Browser.new_context() returns watched context."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                watched = sw.watch(browser, job="test-playwright")
                context = watched.new_context()

                assert hasattr(context, "_scrapewatch_wrapped")
                assert context._scrapewatch_wrapped is True

                context.close()
            finally:
                browser.close()

    def test_response_is_captured(self):
        """Navigating to a page captures the response."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                watched = sw.watch(browser, job="test-playwright")
                context = watched.new_context()
                page = context.new_page()

                # Navigate to a simple page
                # Using example.com as it's reliable and fast
                response = page.goto("https://example.com", timeout=10000)

                # Response should have been captured
                assert context._scrapewatch_seen >= 1

                # The response we got should be the real one
                assert response is not None
                assert response.status == 200

                page.close()
                context.close()
            finally:
                browser.close()

    def test_analyzer_processes_events(self):
        """Events go through the analyzer."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                watched = sw.watch(browser, job="test-playwright")
                context = watched.new_context()
                analyzer = context._scrapewatch_analyzer

                before = analyzer.processed_events

                page = context.new_page()
                page.goto("https://example.com", timeout=10000)
                page.close()

                # Wait for analyzer to process
                analyzer.flush()

                assert analyzer.processed_events > before

                context.close()
            finally:
                browser.close()

    def test_multiple_pages_share_context_state(self):
        """Multiple pages in same context share the watcher state."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                watched = sw.watch(browser, job="test-playwright")
                context = watched.new_context()

                page1 = context.new_page()
                page2 = context.new_page()

                page1.goto("https://example.com", timeout=10000)
                page2.goto("https://example.org", timeout=10000)

                # Both pages' responses should be captured
                assert context._scrapewatch_seen >= 2

                page1.close()
                page2.close()
                context.close()
            finally:
                browser.close()


class TestPlaywrightAsyncLive:
    """Tests for Playwright async Browser with real browser."""

    def test_async_browser_wrap(self):
        """Wrapping an async Browser returns WatchedAsyncBrowser."""
        import asyncio

        from playwright.async_api import async_playwright

        async def run_test():
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                try:
                    watched = sw.watch(browser, job="test-playwright-async")

                    assert hasattr(watched, "_scrapewatch_wrapped")
                    assert watched._scrapewatch_wrapped is True
                finally:
                    await browser.close()

        asyncio.run(run_test())

    def test_async_response_is_captured(self):
        """Async navigation captures responses."""
        import asyncio

        from playwright.async_api import async_playwright

        async def run_test():
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                try:
                    watched = sw.watch(browser, job="test-playwright-async")
                    context = await watched.new_context()
                    page = await context.new_page()

                    await page.goto("https://example.com", timeout=10000)

                    # Response should have been captured
                    assert context._scrapewatch_seen >= 1

                    await page.close()
                    await context.close()
                finally:
                    await browser.close()

        asyncio.run(run_test())


class TestPlaywrightBrowserContextWrap:
    """Tests for wrapping BrowserContext directly."""

    def test_context_wrap_directly(self):
        """Can wrap a BrowserContext directly."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                context = browser.new_context()
                watched = sw.watch(context, job="test-playwright")

                assert hasattr(watched, "_scrapewatch_wrapped")
                assert watched._scrapewatch_wrapped is True

                watched.close()
            finally:
                browser.close()

    def test_context_wrap_captures_responses(self):
        """Wrapping context directly still captures responses."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                context = browser.new_context()
                watched = sw.watch(context, job="test-playwright")

                page = watched.new_page()
                page.goto("https://example.com", timeout=10000)

                assert watched._scrapewatch_seen >= 1

                page.close()
                watched.close()
            finally:
                browser.close()
