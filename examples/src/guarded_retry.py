"""Example: guarded() protocol with retry.

Throws SwBlocked/SwGarbage on bad verdicts.
Integrates with tenacity for retries.
"""

import requests
import scrapewatch as sw
from tenacity import retry, retry_if_exception_type, stop_after_attempt


@retry(
    retry=retry_if_exception_type(sw.SwBlocked),
    stop=stop_after_attempt(3),
)
def fetch_with_retry(session, url):
    return session.get(url)


def main():
    session = sw.guarded(requests.Session(), job="example-retry")

    try:
        response = fetch_with_retry(session, "https://httpbin.org/html")
        print(f"Success: {response.status_code}")
    except sw.SwBlocked as e:
        print(f"Blocked after retries: {e.verdict}")
    except sw.SwGarbage as e:
        print(f"Garbage: {e.verdict}")


if __name__ == "__main__":
    main()
