"""
测试单个视频 — 导航到 jump_url，捕获播放API
"""
import asyncio
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.async_api import async_playwright

BASE = "https://appzl5apwz41977.h5.xet.pomoho.com"
OUT_DIR = Path(r"D:\zhihu\debug")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 从 all_resources.json 读取第一个资源
with open(OUT_DIR / "all_resources.json", encoding="utf-8") as f:
    resources = json.load(f)

print(f"总资源数: {len(resources)}")
print(f"第一个: {resources[0]}")

# 取第一个资源
r = resources[0]
resource_id = r["resource_id"]
title = r.get("title", "")

# 构建 jump_url
jump_url = f"/v4/course/alive/{resource_id}?type=2&resource_type=4&resource_id={resource_id}&app_id=appzl5apwz41977&pro_id=p_62ee3208e4b0eca59c1f854d&conduit_id=p_62ee3208e4b0eca59c1f854d&conduit_type=live_group"


async def main():
    print(f"测试资源: {title} ({resource_id})")
    print(f"URL: {BASE}{jump_url}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()

        all_responses = []

        async def on_response(response):
            ctype = response.headers.get("content-type", "")
            if "json" not in ctype:
                return
            try:
                body = await response.json()
                all_responses.append({
                    "url": response.url,
                    "method": response.request.method,
                    "post_data": response.request.post_data,
                    "body": body,
                })
            except Exception:
                pass

        page.on("response", on_response)

        # 先登录
        await page.goto(
            f"{BASE}/p/course/column/p_62ee3208e4b0eca59c1f854d?product_id=p_62ee31c5e4b050af23a5b3e7",
            wait_until="domcontentloaded", timeout=30000,
        )
        print("请在浏览器中登录...")

        for _ in range(300):
            await asyncio.sleep(1)
            if "login" not in page.url and "auth" not in page.url:
                await asyncio.sleep(3)
                if "login" not in page.url and "auth" not in page.url:
                    break
        else:
            print("登录超时")
            return

        print("登录成功！导航到视频页面...")
        all_responses.clear()

        # 导航到视频播放页面
        await page.goto(f"{BASE}{jump_url}", wait_until="networkidle", timeout=30000)
        await asyncio.sleep(10)  # 等待视频播放器初始化和API调用

        # 保存所有捕获的响应
        print(f"捕获了 {len(all_responses)} 个API响应")

        # 找出视频相关的
        video_apis = []
        for resp in all_responses:
            url = resp["url"]
            body = resp["body"]
            # 检查是否包含播放URL
            if isinstance(body, dict):
                data = body.get("data", {})
                if isinstance(data, dict):
                    has_play = any(k in data for k in
                                   ("play_url", "video_url", "videoUrl", "video_urls",
                                    "m3u8", "live_url", "stream_url", "hls_url",
                                    "flv_url", "rtmp_url"))
                    if has_play:
                        video_apis.append(resp)
                        print(f"  [VIDEO] {url[:100]}")
                        print(f"    data_keys: {list(data.keys())}")
                        for k in data:
                            val = str(data[k])[:200]
                            print(f"    {k}: {val}")

        # 如果没找到明确的play_url，搜索所有包含url的响应
        if not video_apis:
            print("\n未找到明显播放API，搜索所有含URL的响应...")
            for resp in all_responses:
                body_str = json.dumps(resp["body"], ensure_ascii=False)
                if ".m3u8" in body_str or "play_url" in body_str or "video" in body_str.lower():
                    print(f"\n  [m3u8匹配] {resp['url'][:100]}")
                    print(f"  body前500字: {body_str[:500]}")

        # 保存所有用于分析
        with open(OUT_DIR / "video_page_responses.json", "w", encoding="utf-8") as f:
            json.dump(all_responses, f, ensure_ascii=False, indent=2, default=str)

        await browser.close()
        print(f"\n所有响应已保存: {OUT_DIR / 'video_page_responses.json'}")


asyncio.run(main())
