"""Scrapewatch domain exceptions.

These exceptions are raised in guarded mode (sw.guarded()) when
verdicts indicate blocked or garbage responses.
"""

from .verdict import Verdict


class SwBlocked(Exception):
    """Raised when a response is classified as blocked.

    In guarded mode, challenge pages, captcha walls, and access denied
    responses raise this exception — even when served with HTTP 200.

    Attributes:
        verdict: The Verdict that triggered this exception
        response: The original response object
    """

    def __init__(self, verdict: Verdict, response: object) -> None:
        self.verdict = verdict
        self.response = response
        super().__init__(f"blocked: {verdict.detector_id} — {verdict.reason}")


class SwGarbage(Exception):
    """Raised when a response is classified as garbage.

    In guarded mode, empty shells, login walls, geo-blocks, and soft-404s
    raise this exception.

    Attributes:
        verdict: The Verdict that triggered this exception
        response: The original response object
    """

    def __init__(self, verdict: Verdict, response: object) -> None:
        self.verdict = verdict
        self.response = response
        super().__init__(f"garbage: {verdict.detector_id} — {verdict.reason}")


__all__ = ["SwBlocked", "SwGarbage"]
