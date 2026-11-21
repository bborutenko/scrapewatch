"""Example: watch() protocol with Playwright.

Supports both sync and async Playwright API.
"""

from playwright.sync_api import sync_playwright
import scrapewatch as sw


def sync_example():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = sw.watch(browser.new_context(), job="example-pw-sync")
        
        page = context.new_page()
        page.goto("https://httpbin.org/html")
        
        print(f"Title: {page.title()}")
        
        browser.close()


async def async_example():
    from playwright.async_api import async_playwright
    
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = sw.watch(await browser.new_context(), job="example-pw-async")
        
        page = await context.new_page()
        await page.goto("https://httpbin.org/html")
        
        print(f"Title: {await page.title()}")
        
        await browser.close()


if __name__ == "__main__":
    import asyncio
    
    sync_example()
    asyncio.run(async_example())
