CLOUDFLARE_RULE_PATH = None

def pytest_configure(config):
    import tempfile
    from pathlib import Path
    
    global CLOUDFLARE_RULE_PATH
    
    rule_content = """
id: cloudflare-challenge
name: Cloudflare challenge / interstitial
verdict: blocked
severity: high
match:
  status_hint: [403, 429, 503]
  any_of:
    - title_re: ["Just a moment..."]
    - body_re: ["cdn-cgi/challenge-platform", "challenges.cloudflare.com"]
"""
    
    tmpdir = Path(tempfile.gettempdir()) / "scrapewatch-test-rules"
    tmpdir.mkdir(exist_ok=True)
    rule_file = tmpdir / "cloudflare.yaml"
    rule_file.write_text(rule_content)
    CLOUDFLARE_RULE_PATH = str(rule_file)

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


#: fake-200: a challenge page served behind HTTP 200 — the failure mode
#: scrapewatch exists for (CONCEPTS.md "fake-200")
CHALLENGE_PAGE = (
    b"<html><head><title>Just a moment...</title></head>"
    b"<body><script src='https://challenges.cloudflare.com/turnstile/v0/api.js'></script>"
    b"</body></html>"
)


class _PricesHandler(BaseHTTPRequestHandler):
    """Serves an HTML body on every path; ``/redirect`` bounces to ``/final``."""

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
        body = b"<html>prices</html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # keep pytest output clean


@pytest.fixture()
def cloudflare_rule_path() -> str:
    return CLOUDFLARE_RULE_PATH


@pytest.fixture()
def local_server() -> str:
    """Base URL of a throwaway HTTP server bound to an ephemeral port."""
    server = HTTPServer(("127.0.0.1", 0), _PricesHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
