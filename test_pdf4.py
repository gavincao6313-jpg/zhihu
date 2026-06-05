"""搜索页面HTML中的PDF链接"""
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

        await page.goto(f"{BASE}/p/course/video/{VID}?product_id={PID}", wait_until="networkidle", timeout=30000)
        print("请登录...")
        for _ in range(300):
            await asyncio.sleep(1)
            if "login" not in page.url: break
        print("登录成功!\n")

        # 获取页面完整HTML
        html = await page.content()

        # 搜索pdf链接
        pdf_links = re.findall(r'https?://[^"\s]*?\.pdf[^"\s]*', html)
        print(f"HTML中找到 {len(pdf_links)} 个PDF链接:")
        for link in set(pdf_links):
            print(f"  {link[:200]}")

        # 搜索file链接
        file_links = re.findall(r'https?://[^"\s]*?/file/[^"\s]*', html)
        print(f"\nfile链接: {len(file_links)}")
        for link in set(file_links)[:10]:
            print(f"  {link[:200]}")

        # 搜索download链接
        dl_links = re.findall(r'https?://[^"\s]*?(download|resource)[^"\s]*', html)
        print(f"\ndownload/resource链接: {len(dl_links)}")
        for link in set(dl_links)[:10]:
            print(f"  {link[:200]}")

        # 检查window.__INITIAL_STATE__
        init = await page.evaluate("() => window.__INITIAL_STATE__")
        if init:
            init_str = json.dumps(init, ensure_ascii=False)
            pdfs = re.findall(r'https?://[^"\s]*?\.pdf[^"\s]*', init_str)
            print(f"\n__INITIAL_STATE__中PDF: {len(pdfs)}")
            for p in pdfs:
                print(f"  {p[:200]}")

        await browser.close()

asyncio.run(main())
