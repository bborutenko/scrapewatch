"""Pytest configuration and fixtures for scrapewatch tests."""

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from scrapewatch.config import configure, reset_settings
from scrapewatch.core.event import Event, JobRef
from scrapewatch.core.verdict import Status, Verdict
from scrapewatch.storage.models import Run
from scrapewatch.storage.sqlite import Storage


# Path to fixtures directory
FIXTURES_DIR = Path(__file__).parent / "fixtures"
RULES_DIR = FIXTURES_DIR / "rules"
HTML_DIR = FIXTURES_DIR / "html"


#: fake-200: a challenge page served behind HTTP 200 — the failure mode
#: scrapewatch exists for (CONCEPTS.md "fake-200")
CHALLENGE_HTML = (HTML_DIR / "challenge.html").read_text()
CHALLENGE_PAGE = CHALLENGE_HTML.encode("utf-8")

PRICES_HTML = (HTML_DIR / "prices.html").read_text()
PRICES_PAGE = PRICES_HTML.encode("utf-8")


class _TestServerHandler(BaseHTTPRequestHandler):
    """Serves test HTML pages on various paths."""

    def do_GET(self):
        if self.path.startswith("/redirect"):
            self.send_response(302)
            self.send_header("Location", "/final")
            self.end_headers()
            return
        if self.path.startswith("/challenge"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(CHALLENGE_PAGE)))
            self.end_headers()
            self.wfile.write(CHALLENGE_PAGE)
            return
        # Default: return prices page (for integration tests)
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(PRICES_PAGE)))
        self.end_headers()
        self.wfile.write(PRICES_PAGE)

    def log_message(self, *args):
        pass  # keep pytest output clean


# ============================================================================
# Path Fixtures
# ============================================================================


@pytest.fixture()
def cloudflare_rule_path() -> str:
    """Path to the cloudflare.yaml rule fixture."""
    return str(RULES_DIR / "cloudflare.yaml")


@pytest.fixture()
def rules_dir() -> str:
    """Path to the rules fixtures directory."""
    return str(RULES_DIR)


@pytest.fixture()
def temp_db_path(tmp_path: Path) -> str:
    """Create a temporary database file for each test."""
    db_path = tmp_path / "test.db"
    return str(db_path)


@pytest.fixture()
def temp_rules_dir(tmp_path: Path) -> str:
    """Create a temporary rules directory for each test."""
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    return str(rules_dir)


# ============================================================================
# HTML Content Fixtures
# ============================================================================


@pytest.fixture()
def challenge_html() -> str:
    """Cloudflare challenge page HTML content."""
    return CHALLENGE_HTML


@pytest.fixture()
def prices_html() -> str:
    """Normal prices page HTML content."""
    return PRICES_HTML


@pytest.fixture()
def local_server() -> str:
    """Base URL of a throwaway HTTP server bound to an ephemeral port."""
    server = HTTPServer(("127.0.0.1", 0), _TestServerHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


# ============================================================================
# Storage Fixtures
# ============================================================================


@pytest.fixture()
def storage(temp_db_path: str):
    """Create a Storage instance with a temporary database."""
    configure(db_path=temp_db_path)
    store = Storage(db_path=temp_db_path)
    yield store
    store.close()
    reset_settings()


# ============================================================================
# Event/Verdict/Run Fixtures
# ============================================================================


@pytest.fixture()
def event() -> Event:
    """Create a sample Event for testing."""
    return Event(
        url="https://example.com/prices",
        job=JobRef(name="ebay-prices", run_id="run-001"),
        captured_at="2026-11-21T12:00:00+00:00",
        status_code=200,
        headers={"content-type": "text/html"},
        content_type="text/html",
        body_sample="<html>prices</html>",
        body_hash="ab" * 32,
        body_length=20,
        latency_ms=150.5,
    )


@pytest.fixture()
def verdict() -> Verdict:
    """Create a sample Verdict for testing."""
    return Verdict(
        status=Status.OK,
        detector_id=None,
        reason="no detector fired",
        confidence=1.0,
        evidence={},
        event_hash="cd" * 32,
    )


@pytest.fixture()
def blocked_verdict() -> Verdict:
    """Create a blocked Verdict for testing."""
    return Verdict(
        status=Status.BLOCKED,
        detector_id="cloudflare-challenge",
        reason="Cloudflare interstitial detected",
        confidence=0.95,
        evidence={"matched_signatures": ["title_re: Just a moment"]},
        event_hash="ef" * 32,
    )


@pytest.fixture()
def run() -> Run:
    """Create a sample Run for testing."""
    return Run.create(run_id="run-001", job="ebay-prices")
