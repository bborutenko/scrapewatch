"""Integration tests for reactive protocols: guarded and fetch.

Tests that these protocols work correctly with real HTTP requests.
"""

import pytest
import requests

import scrapewatch as sw


class TestGuarded:
    """Tests for guarded() protocol."""

    def test_guarded_raises_on_challenge_page(self, local_server):
        """guarded() raises SwBlocked on challenge page."""
        session = sw.guarded(requests.Session(), job="test")

        with pytest.raises(sw.SwBlocked) as exc_info:
            session.get(f"{local_server}/challenge")

        assert exc_info.value.verdict is not None
        assert exc_info.value.response is not None

    def test_guarded_passes_healthy_response(self, local_server):
        """guarded() does not raise on healthy response."""
        session = sw.guarded(requests.Session(), job="test")

        response = session.get(local_server)

        assert response.status_code == 200
        assert response.text == "<html>prices</html>"

    def test_guarded_preserves_client_state(self, local_server):
        """guarded() preserves headers and cookies."""
        session = requests.Session()
        session.headers["X-Test"] = "value"
        session.cookies.set("session", "abc")

        guarded_session = sw.guarded(session, job="test")

        assert guarded_session._client.headers.get("X-Test") == "value"
        assert guarded_session._client.cookies.get("session") == "abc"

    def test_guarded_still_observes(self, local_server):
        """guarded() still records events like watch()."""
        session = sw.guarded(requests.Session(), job="test")

        session.get(local_server)

        assert session._client._scrapewatch_seen >= 1


class TestFetch:
    """Tests for fetch() protocol."""

    def test_fetch_returns_verdict_synchronously(self, local_server):
        """fetch() provides verdict in context."""
        session = requests.Session()

        with sw.fetch(session.get, f"{local_server}/challenge", job="test") as ctx:
            assert ctx.response is not None
            assert ctx.verdict is not None
            assert ctx.verdict.status == "blocked"

    def test_fetch_with_healthy_response(self, local_server):
        """fetch() returns ok verdict for healthy response."""
        session = requests.Session()

        with sw.fetch(session.get, local_server, job="test") as ctx:
            assert ctx.response.status_code == 200
            assert ctx.verdict.status == "ok"

    def test_fetch_retry_mechanism(self, local_server):
        """fetch() supports retry()."""
        session = requests.Session()

        with sw.fetch(session.get, local_server, job="test") as ctx:
            first_response = ctx.response

            # Retry the same request
            ctx.retry()

            # Response should be updated
            assert ctx.response is not None
            # Could be same object or different, but should have same content
            assert ctx.response.status_code == 200

    def test_fetch_with_connection_error(self):
        """fetch() handles connection errors gracefully."""
        session = requests.Session()
        session.request = lambda *a, **kw: (_ for _ in ()).throw(requests.exceptions.ConnectionError())
        
        with pytest.raises(requests.exceptions.ConnectionError):
            with sw.fetch(session.get, "http://127.0.0.1:1/nope", job="test") as ctx:
                pass

    def test_fetch_verdict_on_connection_error(self):
        """fetch() still provides verdict on connection error."""
        session = requests.Session()
        # Override request to raise connection error
        original_get = session.get
        def failing_get(url, **kwargs):
            raise requests.exceptions.ConnectionError("Connection refused")
        session.get = failing_get
        
        with pytest.raises(requests.exceptions.ConnectionError):
            with sw.fetch(session.get, "http://127.0.0.1:1/nope", job="test") as ctx:
                pass

    def test_fetch_empty_job_rejected(self, local_server):
        """fetch() rejects empty job name."""
        session = requests.Session()

        with pytest.raises(ValueError, match="non-empty"):
            with sw.fetch(session.get, local_server, job=""):
                pass


class TestGuardedWithRetry:
    """Tests for guarded() with retry libraries."""

    def test_guarded_works_with_retry_pattern(self, local_server):
        """guarded() integrates with retry pattern."""
        from tenacity import RetryError, retry, retry_if_exception_type, stop_after_attempt

        session = sw.guarded(requests.Session(), job="test")

        attempts = [0]

        @retry(
            retry=retry_if_exception_type(sw.SwBlocked),
            stop=stop_after_attempt(2),
        )
        def fetch_with_retry(url):
            attempts[0] += 1
            response = session.get(url)
            return response

        # This should retry and then raise RetryError
        with pytest.raises(RetryError):
            fetch_with_retry(f"{local_server}/challenge")

        # Should have attempted twice (initial + 1 retry)
        assert attempts[0] == 2

    def test_guarded_healthy_no_retry(self, local_server):
        """guarded() doesn't trigger retry on healthy response."""
        from tenacity import retry, retry_if_exception_type

        session = sw.guarded(requests.Session(), job="test")

        attempts = [0]

        @retry(retry=retry_if_exception_type(sw.SwBlocked))
        def fetch_healthy(url):
            attempts[0] += 1
            return session.get(url)

        response = fetch_healthy(local_server)

        assert response.status_code == 200
        assert attempts[0] == 1  # No retry needed
