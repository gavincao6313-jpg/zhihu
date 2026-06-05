"""测试视频类型播放API"""
import asyncio, json, sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from playwright.async_api import async_playwright

VIDEO_URL = "https://appzl5apwz41977.h5.xet.pomoho.com/p/course/video/v_6537d59de4b064a82f11465f?product_id=p_6537d3b9e4b064a82f114627"
BASE = "https://appzl5apwz41977.h5.xet.pomoho.com"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
        ctx = await browser.new_context()
        page = await ctx.new_page()

        all_responses = []
        async def on_response(resp):
            if "json" in (resp.headers.get("content-type","")):
                try:
                    all_responses.append({"url": resp.url, "method": resp.request.method, "body": await resp.json()})
                except: pass
        page.on("response", on_response)

        await page.goto(VIDEO_URL, wait_until="domcontentloaded", timeout=30000)
        print("请登录...")
        for _ in range(300):
            await asyncio.sleep(1)
            if "login" not in page.url:
                await asyncio.sleep(3)
                if "login" not in page.url: break
        else:
            print("超时"); return

        print("登录成功！等待视频播放器加载...")
        await asyncio.sleep(8)

        # 找包含播放URL的API
        video_apis = []
        for r in all_responses:
            body = r.get("body", {})
            if isinstance(body, dict):
                d = body.get("data", {})
                if isinstance(d, dict):
                    keys = list(d.keys())
                    has_url = any(k for k in keys if k.lower() in ("play_url","video_url","videourl","url","m3u8","encrypt"))
                    if has_url:
                        video_apis.append(r)
                        print(f"\n[{r['url'][:100]}]")
                        print(f"data keys: {keys}")
                        for k, v in d.items():
                            if isinstance(v, (str,int)):
                                print(f"  {k}: {str(v)[:200]}")

        if not video_apis:
            print("\n未直接找到，搜索m3u8...")
            for r in all_responses:
                body_str = json.dumps(r["body"])
                if ".m3u8" in body_str:
                    print(f"\n[m3u8命中] {r['url'][:100]}")
                    print(body_str[:500])

        # 保存所有
        with open(r"D:\zhihu\debug\video_api_test.json", "w", encoding="utf-8") as f:
            json.dump(all_responses, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n全部 {len(all_responses)} 个响应已保存")

        await browser.close()

asyncio.run(main())
