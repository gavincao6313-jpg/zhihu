"""测试PDF - 查所有含file/pdf/resource的API"""
import asyncio, json, sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from playwright.async_api import async_playwright

BASE = "https://appzl5apwz41977.h5.xet.pomoho.com"
COL = "p_6a044874e4b0694c35082de8"
PID = "p_62ee31c5e4b050af23a5b3e7"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
        ctx = await browser.new_context()
        page = await ctx.new_page()

        all_responses = []
        async def on_resp(resp):
            if "json" in (resp.headers.get("content-type","")):
                try:
                    all_responses.append({"url": resp.url, "body": await resp.json()})
                except: pass
        page.on("response", on_resp)

        # 先登录
        await page.goto(f"{BASE}/p/course/column/{COL}?product_id={PID}", wait_until="domcontentloaded", timeout=30000)
        print("请登录...")
        for _ in range(300):
            await asyncio.sleep(1)
            if "login" not in page.url: break

        print("登录成功!\n")

        # 打开第一个视频页，点击可能的"课件"按钮
        VID = "v_6a1e479ae4b0694c35129ca7"
        await page.goto(f"{BASE}/p/course/video/{VID}?product_id={PID}", wait_until="networkidle", timeout=30000)
        await asyncio.sleep(3)

        # 尝试点击可能的课件/资料按钮
        click_selectors = [
            "text=课件", "text=资料", "text=下载", "text=PDF",
            "[class*=courseware]", "[class*=material]", "[class*=file]",
            "[class*=download]", "[class*=tab]", ".tab-item",
            "a[href*='pdf']", "a[href*='file']",
        ]
        for sel in click_selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    await el.click()
                    await asyncio.sleep(2)
            except: pass

        await asyncio.sleep(3)

        # 检查所有含file/pdf的API
        print("=== 文件/PDF相关API ===")
        for r in all_responses:
            url = r["url"]
            body = r["body"]
            body_str = json.dumps(body)
            if "pdf" in url.lower() or "file" in url.lower() or ".pdf" in body_str or "download" in url.lower():
                print(f"\n[{url}]")
                print(body_str[:500])

        # 列出所有唯一API
        print("\n=== 所有唯一API ===")
        urls = sorted(set(r["url"].split("?")[0] for r in all_responses))
        for u in urls:
            print(u.replace(BASE, ""))

        await browser.close()

asyncio.run(main())
