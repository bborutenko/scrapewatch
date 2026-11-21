"""Example: fetch() protocol for reactive handling.

Get verdict synchronously and react at decision point.
"""

import requests
import scrapewatch as sw


def rotate_proxy():
    print("Rotating proxy...")


def main():
    session = requests.Session()

    sw.configure(rules_dir="rules")

    with sw.fetch(session.get, "https://httpbin.org/html", job="example-fetch") as ctx:
        print(f"Status: {ctx.response.status_code}")
        print(f"Verdict: {ctx.verdict.status}")

        if ctx.verdict.status == "blocked":
            rotate_proxy()
            ctx.retry()
            print(f"After retry: {ctx.verdict.status}")
        elif ctx.verdict.status == "garbage":
            print("Skipping garbage response")
        else:
            data = ctx.response.text
            print(f"Got {len(data)} bytes")


if __name__ == "__main__":
    main()
