"""WatchedClient/WatchedAsyncClient against a real local HTTP server.

Tests that httpx interceptors actually capture requests and process events.
"""

import pytest

import scrapewatch as sw

# httpx is in dev dependencies, so it should be available
import httpx


class TestHttpxSyncLive:
    """Tests for httpx.Client (sync) with real HTTP requests."""

    def test_real_request_is_observed(self, local_server):
        """Each request through watched client is observed."""
        client = httpx.Client()
        watched = sw.watch(client, job="test-httpx")

        response = watched.get(local_server)

        assert response.status_code == 200
        assert watched._scrapewatch_seen == 1

    def test_multiple_requests_are_counted(self, local_server):
        """Multiple requests are all observed."""
        client = httpx.Client()
        watched = sw.watch(client, job="test-httpx")

        watched.get(local_server)
        watched.get(local_server)
        watched.get(local_server)

        assert watched._scrapewatch_seen == 3

    def test_redirect_yields_one_event(self, local_server):
        """Redirect counts as one event (the final response)."""
        client = httpx.Client(follow_redirects=True)
        watched = sw.watch(client, job="test-httpx")

        response = watched.get(f"{local_server}/redirect")

        assert response.status_code == 200
        assert watched._scrapewatch_seen == 1

    def test_event_is_processed_by_analyzer(self, local_server):
        """Event goes through the analyzer and is processed."""
        client = httpx.Client()
        watched = sw.watch(client, job="test-httpx")
        analyzer = watched._scrapewatch_analyzer

        before = analyzer.processed_events
        watched.get(local_server)
        analyzer.flush()

        assert analyzer.processed_events == before + 1
        assert analyzer.analyzer_errors == 0

    def test_challenge_page_is_processed(self, local_server):
        """Challenge page (fake-200) is captured and processed."""
        client = httpx.Client()
        watched = sw.watch(client, job="test-httpx")
        analyzer = watched._scrapewatch_analyzer

        before = analyzer.processed_events
        response = watched.get(f"{local_server}/challenge")
        analyzer.flush()

        assert response.status_code == 200
        assert analyzer.processed_events == before + 1
        assert analyzer.analyzer_errors == 0

    def test_connection_error_becomes_event(self):
        """Connection error is captured as event with status_code=None."""
        client = httpx.Client(timeout=0.1)
        watched = sw.watch(client, job="test-httpx")
        analyzer = watched._scrapewatch_analyzer

        before = analyzer.processed_events

        with pytest.raises(httpx.ConnectError):
            watched.get("http://127.0.0.1:1/nope")

        analyzer.flush()
        assert analyzer.processed_events == before + 1

    def test_response_is_unchanged(self, local_server):
        """User sees the same response as without watch."""
        client = httpx.Client()
        watched = sw.watch(client, job="test-httpx")

        response = watched.get(local_server)

        assert response.text == "<html>prices</html>"
        assert response.headers["content-type"] == "text/html"

    def test_client_state_is_preserved(self, local_server):
        """Headers and cookies are preserved after wrapping."""
        client = httpx.Client(
            headers={"X-Custom": "test"},
            cookies={"session": "abc123"},
        )
        watched = sw.watch(client, job="test-httpx")

        # Headers and cookies should be preserved
        assert watched.headers.get("X-Custom") == "test"
        assert watched.cookies.get("session") == "abc123"

        # Should work for requests
        response = watched.get(local_server)
        assert response.status_code == 200


class TestHttpxAsyncLive:
    """Tests for httpx.AsyncClient with real HTTP requests."""

    def test_async_request_is_observed(self, local_server):
        """Each async request through watched client is observed."""
        import asyncio

        async def run_test():
            client = httpx.AsyncClient()
            watched = sw.watch(client, job="test-httpx-async")

            response = await watched.get(local_server)

            assert response.status_code == 200
            assert watched._scrapewatch_seen == 1

        asyncio.run(run_test())

    def test_async_multiple_requests_are_counted(self, local_server):
        """Multiple async requests are all observed."""
        import asyncio

        async def run_test():
            client = httpx.AsyncClient()
            watched = sw.watch(client, job="test-httpx-async")

            await watched.get(local_server)
            await watched.get(local_server)
            await watched.get(local_server)

            assert watched._scrapewatch_seen == 3

        asyncio.run(run_test())

    def test_async_event_is_processed_by_analyzer(self, local_server):
        """Async event goes through the analyzer and is processed."""
        import asyncio

        async def run_test():
            client = httpx.AsyncClient()
            watched = sw.watch(client, job="test-httpx-async")
            analyzer = watched._scrapewatch_analyzer

            before = analyzer.processed_events
            await watched.get(local_server)
            analyzer.flush()

            assert analyzer.processed_events == before + 1
            assert analyzer.analyzer_errors == 0

        asyncio.run(run_test())

    def test_async_connection_error_becomes_event(self):
        """Async connection error is captured as event."""
        import asyncio

        async def run_test():
            client = httpx.AsyncClient(timeout=0.1)
            watched = sw.watch(client, job="test-httpx-async")
            analyzer = watched._scrapewatch_analyzer

            before = analyzer.processed_events

            with pytest.raises(httpx.ConnectError):
                await watched.get("http://127.0.0.1:1/nope")

            analyzer.flush()
            assert analyzer.processed_events == before + 1

        asyncio.run(run_test())

    def test_async_response_is_unchanged(self, local_server):
        """User sees the same response as without watch."""
        import asyncio

        async def run_test():
            client = httpx.AsyncClient()
            watched = sw.watch(client, job="test-httpx-async")

            response = await watched.get(local_server)

            assert response.text == "<html>prices</html>"

        asyncio.run(run_test())
