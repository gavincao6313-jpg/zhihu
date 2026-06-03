"""Save xiaoe auth state via manual login in headed browser.

Usage: python save_xiaoe_auth.py <xiaoe_live_url>
"""
from pathlib import Path
from playwright.sync_api import sync_playwright
import sys

if len(sys.argv) < 2 or not sys.argv[1].strip():
    print("Usage: python save_xiaoe_auth.py <xiaoe_live_url>")
    sys.exit(1)

url = sys.argv[1].strip()
out_path = str(Path(__file__).parent / "zhihu_auth_state_xiaoe.json")

print("Opening browser for xiaoe login...")
print(f"URL: {url[:120]}...")
print(f"Auth will be saved to: {out_path}")
print()
print("=== 请在浏览器中完成小鹅通登录（微信扫码/手机号）===")
print("=== 看到直播画面后，回到终端按 Enter 保存 auth state ===")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context(
        viewport={"width": 1280, "height": 720},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
        ),
    )
    page = context.new_page()

    # Antidetection
    page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => false });
        window.chrome = { runtime: {} };
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    """)

    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    print(f"Current URL: {page.url[:150]}")

    input("\n按 Enter 保存 auth state 并退出...")

    context.storage_state(path=out_path)
    print(f"Saved: {out_path}")
    browser.close()
    print("Done.")
