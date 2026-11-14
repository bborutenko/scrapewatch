"""requests integration — imported only when a requests client is wrapped.

This module is the only place allowed to ``import requests`` at top level:
it is never imported unless the caller already holds a ``requests.Session``,
which proves the library is installed (ADR-5).
"""

from typing import Any

import requests


class WatchedSession(requests.Session):
    """Session subclass that routes every response through the capture hook."""

    def __init__(self, *, job: str) -> None:
        super().__init__()
        self._scrapewatch_job = job
        self._scrapewatch_seen = 0

    def request(self, *args: Any, **kwargs: Any) -> requests.Response:
        response = super().request(*args, **kwargs)
        self._scrapewatch_observe(response)
        return response

    def _scrapewatch_observe(self, response: requests.Response) -> None:
        # engine.observe(Event(...)) attaches here once the core exists
        # (ADR-2); the counter only proves the interception point is live.
        self._scrapewatch_seen += 1


def wrap(client: requests.Session, *, job: str) -> WatchedSession:
    """Build a ``WatchedSession`` carrying over the caller's session state."""

    watched = WatchedSession(job=job)
    watched.headers.update(client.headers)
    watched.cookies.update(client.cookies)
    watched.auth = client.auth
    watched.proxies = client.proxies
    watched.params = client.params
    watched.verify = client.verify
    watched.cert = client.cert
    watched.trust_env = client.trust_env

    for prefix, adapter in client.adapters.items():
        watched.mount(prefix, adapter)
        
    return watched
