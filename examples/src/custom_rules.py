"""Example: Custom rule files.

Override packaged rules or add your own detectors.
"""

import requests
import scrapewatch as sw


def main():
    custom_rules = [
        "my-rules/blocked.yaml",
        "my-rules/garbage.yaml",
    ]

    session = sw.watch(
        requests.Session(),
        job="example-custom",
        rules=custom_rules,
    )

    response = session.get("https://httpbin.org/html")
    print(f"Status: {response.status_code}")


# Example custom rule file content (save as my-rules/blocked.yaml):
"""
id: my-custom-blocked
name: My custom challenge detector
verdict: blocked
severity: high
match:
  any_of:
    - title_re: ["Access Denied"]
    - body_re: ["challenge-platform", "bot-detected"]
"""

if __name__ == "__main__":
    main()
