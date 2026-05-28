import asyncio
from playwright.async_api import async_playwright

async def get_title():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            storage_state="d:/zhihu/zhihu_url/zhihu_auth_state.json"
        )
        page = await ctx.new_page()
        await page.goto(
            "https://www.zhihu.com/xen/training/live/room/2013265166804997499/2013265169636139193?is_hybrid=1",
            timeout=15000,
            wait_until="domcontentloaded",
        )
        await page.wait_for_timeout(3000)
        title = await page.title()
        # Write to file to avoid encoding issues
        with open("d:/zhihu/zhihu_url/runs/page_title_live-20260528.txt", "w", encoding="utf-8") as f:
            f.write(title)
        print(f"Title saved. Length: {len(title)} chars")
        await browser.close()

asyncio.run(get_title())
