"""点击"相关资料"标签，捕获PDF列表API"""
import asyncio, json, re, sys
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

        all_responses = []
        async def on_resp(resp):
            if "json" in (resp.headers.get("content-type","")):
                try:
                    all_responses.append({"url": resp.url, "body": await resp.json()})
                except: pass
        page.on("response", on_resp)

        await page.goto(f"{BASE}/p/course/video/{VID}?product_id={PID}", wait_until="networkidle", timeout=30000)
        print("请登录...")
        for _ in range(300):
            await asyncio.sleep(1)
            if "login" not in page.url: break
        print("登录成功!\n")

        await asyncio.sleep(5)

        all_responses.clear()

        # 尝试点击"相关资料"
        click_texts = ["相关资料", "资料", "课件", "文件", "相关材料", "下载"]
        click_selectors = [
            "text=相关资料", "text=资料", "text=课件", "text=文件",
            "[class*=material]", "[class*=courseware]", "[class*=resource]",
            "[class*=file]", "[class*=download]", "[class*=attachment]",
            ".tab-item", ".tab", "[role=tab]",
            "span", "div",
        ]

        print("尝试点击'相关资料'...")
        clicked = False
        for sel in click_texts:
            try:
                el = await page.query_selector(f"text={sel}")
                if el:
                    await el.click()
                    print(f"点击了: text={sel}")
                    clicked = True
                    await asyncio.sleep(3)
                    break
            except: pass

        if not clicked:
            # 尝试找所有可见文本
            texts = await page.evaluate("""
                () => [...document.querySelectorAll('span, div, a, button, li, .tab-item')]
                    .filter(el => el.offsetParent !== null)
                    .map(el => el.textContent.trim())
                    .filter(t => t.length > 0 && t.length < 20)
                    .slice(0, 50)
            """)
            print(f"页面可见文本: {texts}")

            # 点所有可能的
            for t in texts:
                if any(kw in t for kw in ["资料", "课件", "文件", "文档", "下载", "材料"]):
                    try:
                        el = await page.query_selector(f"text={t}")
                        if el:
                            await el.click()
                            print(f"点击: {t}")
                            await asyncio.sleep(2)
                            break
                    except: pass

        await asyncio.sleep(3)

        # 检查新增的API
        new_apis = [r for r in all_responses]
        print(f"\n捕获了 {len(new_apis)} 个新API响应")

        # 找含file/pdf/url的
        for r in new_apis:
            url = r["url"]
            body_str = json.dumps(r["body"])
            if any(kw in url.lower() or kw in body_str.lower()
                   for kw in ["file", "pdf", "material", "download", "resource"]):
                print(f"\n[{url}]")
                print(body_str[:800])

        # 保存所有
        with open(r"D:\zhihu\debug\pdf_click_test.json", "w", encoding="utf-8") as f:
            json.dump(new_apis, f, ensure_ascii=False, indent=2, default=str)

        await browser.close()

asyncio.run(main())
