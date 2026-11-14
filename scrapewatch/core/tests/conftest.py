"""Shared fixtures: a real local HTTP server for integration and e2e tests."""

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


class _PricesHandler(BaseHTTPRequestHandler):
    """Serves an HTML body on every path; ``/redirect`` bounces to ``/final``."""

    def do_GET(self):
        if self.path.startswith("/redirect"):
            self.send_response(302)
            self.send_header("Location", "/final")
            self.end_headers()
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
