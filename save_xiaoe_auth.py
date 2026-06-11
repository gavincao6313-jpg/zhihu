"""Save xiaoe auth state — auto-detects login and saves without waiting for Enter.

Uses persistent browser profile so cookies survive across launches.
Usage: python save_xiaoe_auth.py <xiaoe_live_url>
"""
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright


def has_xiaoe_login_cookie(state: dict) -> bool:
    for cookie in state.get("cookies", []):
        name = str(cookie.get("name", "")).lower()
        domain = str(cookie.get("domain", "")).lower()
        if name == "ko_token" and ("xiaoeknow" in domain or "xet" in domain or "pomoho" in domain):
            return True
    return False

if len(sys.argv) < 2 or not sys.argv[1].strip():
    print("Usage: python save_xiaoe_auth.py <xiaoe_live_url>")
    sys.exit(1)

url = sys.argv[1].strip()
out_path = Path(__file__).parent / "zhihu_auth_state_xiaoe.json"
user_data_dir = str(Path(__file__).parent / ".playwright-xiaoe-profile")

print(f"URL: {url[:120]}...")
print(f"Auth will be saved to: {out_path}")
print()
print("=== 请在浏览器中完成小鹅通登录（微信扫码/手机号）===")
print("=== 看到直播画面后，脚本将自动检测并保存 ===")

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir,
        headless=False,
        viewport={"width": 1280, "height": 720},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
        ),
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--no-sandbox",
        ],
    )

    page = context.new_page()
    page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => false });
        window.chrome = { runtime: {} };
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    """)

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        print(f"Goto error (continuing): {e}")

    print(f"Current URL: {page.url[:150]}")
    print("Waiting for login to complete (max 120s)...")

    deadline = time.time() + 120
    logged_in = False
    while time.time() < deadline:
        current = page.url.lower()
        if "login" not in current and "auth" not in current:
            logged_in = True
            print(f"Logged in! URL: {page.url[:120]}")
            break
        time.sleep(1)

    if not logged_in:
        print("WARNING: Still on login page after 120s. Auth state will be saved only if ko_token exists.")
        print(f"Current URL: {page.url[:200]}")

    state = context.storage_state()
    if not has_xiaoe_login_cookie(state):
        print("ERROR: 未检测到小鹅通 ko_token，auth state 未保存。")
        print("请确认浏览器中已经登录并能看到直播/回放页面后重新运行。")
        context.close()
        sys.exit(1)

    context.storage_state(path=str(out_path))
    print(f"Saved: {out_path} ({out_path.stat().st_size} bytes)")
    context.close()
    print("Done.")
