"""
API诊断脚本 —— 只捕获和保存API响应，不做下载
用于确定正确的API端点和数据格式
"""
import asyncio
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.async_api import async_playwright

COURSE_URL = "https://appzl5apwz41977.h5.xet.pomoho.com/p/course/column/p_62ee3208e4b0eca59c1f854d?product_id=p_62ee31c5e4b050af23a5b3e7"
OUT_DIR = Path(r"D:\zhihu\debug")
OUT_DIR.mkdir(parents=True, exist_ok=True)


async def main():
    print("API诊断 v1")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()

        # 保存所有JSON响应（完整的，不做过滤）
        all_json = []

        async def on_response(response):
            ctype = response.headers.get("content-type", "")
            if "json" not in ctype:
                return
            try:
                body = await response.json()
                all_json.append({
                    "url": response.url,
                    "status": response.status,
                    "method": response.request.method,
                    "post_data": response.request.post_data,
                    "body": body,
                })
            except Exception:
                pass

        page.on("response", on_response)

        await page.goto(COURSE_URL, wait_until="domcontentloaded", timeout=30000)
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

        print("登录成功！刷新页面...")
        all_json.clear()
        await page.goto(COURSE_URL, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(3)

        # 大量滚动加载所有数据
        print("滚动加载所有课程数据...")
        for i in range(60):
            await page.evaluate("window.scrollBy(0, 1200)")
            await asyncio.sleep(0.8)

        # 点击几个视频触发播放API
        print("点击视频触发播放API...")
        for sel in ["[class*=catalog] [class*=item]", "[class*=chapter] [class*=item]",
                     "[class*=lesson]", "[data-resource-id]", "li"]:
            try:
                els = await page.query_selector_all(sel)
                if len(els) > 2:
                    for idx in range(min(3, len(els))):
                        await els[idx].click()
                        await asyncio.sleep(3)
                    break
            except Exception:
                pass

        await asyncio.sleep(5)

        # 保存全部原始响应
        print(f"保存 {len(all_json)} 个API响应...")

        # 完整保存
        with open(OUT_DIR / "raw_all_responses.json", "w", encoding="utf-8") as f:
            json.dump(all_json, f, ensure_ascii=False, indent=2, default=str)

        # 按API分组统计
        api_groups = {}
        for r in all_json:
            url = r["url"].split("?")[0]
            api_name = url.replace("https://appzl5apwz41977.h5.xet.pomoho.com/", "")
            if api_name not in api_groups:
                api_groups[api_name] = []
            api_groups[api_name].append(r)

        summary = {}
        for name, items in sorted(api_groups.items()):
            summary[name] = {
                "count": len(items),
                "methods": list(set(i["method"] for i in items)),
                "sample_body": items[0]["body"] if items else None,
            }

        with open(OUT_DIR / "api_summary.json", "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

        # 重点：保存 column.items.get 的所有响应
        items_responses = [r for r in all_json if "column.items.get" in r["url"]]
        print(f"\ncolumn.items.get 响应数: {len(items_responses)}")

        all_resources = {}
        for resp in items_responses:
            body = resp["body"]
            if isinstance(body, dict):
                data = body.get("data", {})
                if isinstance(data, dict):
                    items = data.get("list", [])
                    for item in items:
                        rid = item.get("resource_id") or item.get("id", "")
                        if rid:
                            all_resources[rid] = item

        print(f"唯一资源数: {len(all_resources)}")

        # 保存第一个资源的完整结构
        if all_resources:
            first_rid = list(all_resources.keys())[0]
            first_resource = all_resources[first_rid]
            with open(OUT_DIR / "sample_resource.json", "w", encoding="utf-8") as f:
                json.dump(first_resource, f, ensure_ascii=False, indent=2, default=str)
            print(f"示例资源字段: {list(first_resource.keys())}")
            print(f"示例资源: {json.dumps(first_resource, ensure_ascii=False)[:500]}")

        # 重点：保存所有包含 video/play/base_info 的响应
        video_related = [r for r in all_json
                         if any(kw in r["url"] for kw in
                                ("video", "play", "base_info", "resource.info", "getPlayUrl"))]
        print(f"\n视频相关API响应数: {len(video_related)}")

        for i, resp in enumerate(video_related):
            with open(OUT_DIR / f"video_api_{i}.json", "w", encoding="utf-8") as f:
                json.dump(resp, f, ensure_ascii=False, indent=2, default=str)
            body = resp["body"]
            if isinstance(body, dict):
                print(f"  [{i}] {resp['url'][:100]}")
                print(f"      top_keys: {list(body.keys())}")
                if "data" in body and isinstance(body["data"], dict):
                    print(f"      data_keys: {list(body['data'].keys())}")

        # 保存资源列表
        resource_list = []
        for rid, item in all_resources.items():
            resource_list.append({
                "resource_id": rid,
                "title": item.get("resource_name") or item.get("title") or item.get("name", ""),
                "type": item.get("resource_type", "?"),
                "raw_keys": list(item.keys()),
            })
        with open(OUT_DIR / "all_resources.json", "w", encoding="utf-8") as f:
            json.dump(resource_list, f, ensure_ascii=False, indent=2, default=str)

        await browser.close()
        print("\n诊断完成!")
        print(f"所有文件在: {OUT_DIR}")
        print(f"  raw_all_responses.json - 所有API原始响应")
        print(f"  api_summary.json - API分组摘要")
        print(f"  all_resources.json - 所有资源列表")
        print(f"  sample_resource.json - 单个资源完整结构")
        print(f"  video_api_*.json - 视频播放API响应")


if __name__ == "__main__":
    asyncio.run(main())
