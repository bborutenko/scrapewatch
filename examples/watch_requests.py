"""Example: watch() protocol with requests.

Passive mode: wrap a session and all requests are observed.
Verdicts are computed asynchronously in background.
"""

import requests
import scrapewatch as sw


def main():
    session = sw.watch(requests.Session(), job="example-watch")

    response = session.get("https://httpbin.org/html")
    print(f"Status: {response.status_code}")
    print(f"Verdict: {session._scrapewatch_last_verdict}")


if __name__ == "__main__":
    main()
