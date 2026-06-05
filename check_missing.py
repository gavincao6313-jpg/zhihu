"""检查2个缺失视频的get_lookback_list API"""
import asyncio, json, sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from playwright.async_api import async_playwright

MISSING = [
    ("l_63a9ab17e4b030cacaffee4d", "【年底大课】再见2022！"),
    ("l_6358c0c1e4b01126ea9b3e44", "【第九回】从大厂投资方向 看不确定性时代的人才趋势（暂时下线）"),
]
BASE = "https://appzl5apwz41977.h5.xet.pomoho.com"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
        ctx = await browser.new_context()
        page = await ctx.new_page()

        await page.goto(
            f"{BASE}/p/course/column/p_62ee3208e4b0eca59c1f854d",
            wait_until="domcontentloaded", timeout=30000,
        )
        print("请登录...")
        for _ in range(300):
            await asyncio.sleep(1)
            if "login" not in page.url:
                await asyncio.sleep(3)
                if "login" not in page.url:
                    break
        else:
            print("超时"); return

        print("登录成功!\n")
        for rid, title in MISSING:
            url = f"{BASE}/_alive/v3/get_lookback_list?app_id=appzl5apwz41977&alive_id={rid}&protection=0"
            print(f"检查: {title}")
            print(f"  API: {url}")
            resp = await page.evaluate("fetch('" + url + "', {credentials:'include'}).then(r => r.json())")
            print(f"  Response: {json.dumps(resp, ensure_ascii=False, indent=2)[:500]}")
            data = resp.get("data", [])
            if isinstance(data, list) and data:
                for line in data:
                    for s in line.get("line_sharpness", []):
                        print(f"  清晰度: {s.get('name')}, URL: {s.get('url', 'N/A')[:100]}")
            else:
                print(f"  无回放数据!")
            print()

        await browser.close()

asyncio.run(main())
