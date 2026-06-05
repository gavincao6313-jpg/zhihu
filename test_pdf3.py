"""测试不同courseware API"""
import asyncio, json, sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from playwright.async_api import async_playwright

BASE = "https://appzl5apwz41977.h5.xet.pomoho.com"
PID = "p_62ee31c5e4b050af23a5b3e7"
VID = "v_6a1e479ae4b0694c35129ca7"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
        ctx = await browser.new_context()
        page = await ctx.new_page()

        await page.goto(f"{BASE}/p/course/video/{VID}?product_id={PID}", wait_until="domcontentloaded", timeout=30000)
        print("请登录...")
        for _ in range(300):
            await asyncio.sleep(1)
            if "login" not in page.url: break
        print("登录成功!\n")

        # 直接调用各种可能的API
        apis = [
            f"{BASE}/xe.course.business_go.courseware_list.get/2.0.0",
            f"{BASE}/xe.course.business.courseware.list/1.0.0",
            f"{BASE}/xe.course.business_go.courseware_list.get/2.0.0?resource_id={VID}&product_id={PID}",
            f"{BASE}/xe.course.business.material.list/1.0.0",
        ]

        for api_url in apis:
            try:
                result = await page.evaluate("""
                    async ({url, vid, pid}) => {
                        const r = await fetch(url, {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({resource_id: vid, product_id: pid}),
                            credentials: 'include'
                        });
                        if (!r.ok) return {error: r.status};
                        return await r.json();
                    }
                """, {"url": api_url, "vid": VID, "pid": PID})
                print(f"[{api_url.split('/')[-1]}]")
                print(json.dumps(result, ensure_ascii=False)[:500])
                print()
            except Exception as e:
                print(f"[{api_url.split('/')[-1]}] ERR: {e}\n")

        # 也试GET
        get_apis = [
            f"{BASE}/xe.course.business_go.courseware_list.get/2.0.0?resource_id={VID}&product_id={PID}",
        ]
        for api_url in get_apis:
            try:
                result = await page.evaluate("""
                    async ({url}) => {
                        const r = await fetch(url, {credentials: 'include'});
                        return await r.json();
                    }
                """, {"url": api_url})
                print(f"[GET] [{api_url.split('/')[-1]}]")
                print(json.dumps(result, ensure_ascii=False)[:500])
                print()
            except Exception as e:
                print(f"[GET] [{api_url.split('/')[-1]}] ERR: {e}\n")

        await browser.close()

asyncio.run(main())
