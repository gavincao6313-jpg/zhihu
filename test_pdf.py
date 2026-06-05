"""测试PDF API - 导航到一个视频页，捕获所有API"""
import asyncio, json, sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from playwright.async_api import async_playwright

BASE = "https://appzl5apwz41977.h5.xet.pomoho.com"
VID = "v_6a1e479ae4b0694c35129ca7"
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
                    body = await resp.json()
                    all_responses.append({"url": resp.url, "body": body})
                except: pass
        page.on("response", on_resp)

        await page.goto(f"{BASE}/p/course/video/{VID}?product_id={PID}", wait_until="domcontentloaded", timeout=30000)
        print("请登录...")
        for _ in range(300):
            await asyncio.sleep(1)
            if "login" not in page.url: break

        print("登录成功！等待API...")
        await asyncio.sleep(10)  # 等久一点

        # 找courseware相关
        for r in all_responses:
            if "courseware" in r["url"]:
                print(f"\n[{r['url']}]")
                print(json.dumps(r["body"], ensure_ascii=False, indent=2)[:1000])
                print()

        # 看看有哪些API被调用
        urls = set(r["url"].split("?")[0] for r in all_responses)
        cw_related = [u for u in urls if "courseware" in u.lower()]
        print(f"\n课件相关API: {cw_related}")

        await browser.close()

asyncio.run(main())
