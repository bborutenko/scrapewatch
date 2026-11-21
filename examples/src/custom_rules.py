"""Example: Custom rule files via configure().

Set default rules_dir once at startup, then all clients use it automatically.
"""

import requests
import scrapewatch as sw


def main():
    # Configure with custom rules directory
    sw.configure(
        rules_dir="rules/",
        db_path="data/scrapewatch.db",
    )
    
    session = sw.watch(requests.Session(), job="example-configured")
    response = session.get("https://httpbin.org/html")
    print(f"Status: {response.status_code}")


if __name__ == "__main__":
    main()
