"""Example: watch() protocol with httpx.

Both sync and async clients are supported.
"""

import httpx
import scrapewatch as sw


def sync_example():
    client = sw.watch(httpx.Client(), job="example-httpx-sync")
    
    response = client.get("https://httpbin.org/html")
    print(f"Sync: {response.status_code}")


async def async_example():
    client = sw.watch(httpx.AsyncClient(), job="example-httpx-async")
    
    async with client:
        response = await client.get("https://httpbin.org/html")
        print(f"Async: {response.status_code}")


if __name__ == "__main__":
    import asyncio
    
    sync_example()
    asyncio.run(async_example())
