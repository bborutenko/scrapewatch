"""Example: watch() protocol with requests.

Passive mode: wrap a session and all requests are observed.
Verdicts are computed asynchronously in background.
"""

import requests
import scrapewatch as sw


def main():
    # Configure scrapewatch at startup
    sw.configure(
        db_path="data/scrapewatch.db",
        rules_dir="rules/",
    )
    
    session = sw.watch(requests.Session(), job="example-watch")

    response = session.get("https://httpbin.org/html")
    print(f"Status: {response.status_code}")
    print(f"Content length: {len(response.text)}")


if __name__ == "__main__":
    main()
