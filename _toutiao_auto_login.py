"""Auto-detect Toutiao login and save auth state - no input() needed.
Polls for auth cookies every second; auto-saves when login detected.
Close the browser when prompted or press Ctrl+C.
"""
import json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))

from toutiao_common import (
    ANTI_DETECTION_ARGS,
    ANTI_DETECTION_INIT_SCRIPT,
    USER_AGENT,
    TOUTIAO_AUTH_STATE,
    DEFAULT_TOUTIAO_HOME_URL,
    ensure_dirs,
)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    raise RuntimeError("playwright not installed")

ensure_dirs()

# Must have at LEAST sso_auth to consider login complete (ttwid alone is just tracking)
REQUIRED_AUTH = {"sso_auth"}
NICE_TO_HAVE = {"ttwid", "tt_webid", "MONITOR_WEB_ID"}
POLL_TIMEOUT = 300  # max 5 minutes

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, args=ANTI_DETECTION_ARGS)
    context = browser.new_context(
        viewport={"width": 1280, "height": 900},
        locale="zh-CN",
        user_agent=USER_AGENT,
    )
    context.add_init_script(ANTI_DETECTION_INIT_SCRIPT)

    page = context.new_page()
    page.goto(DEFAULT_TOUTIAO_HOME_URL, wait_until="domcontentloaded", timeout=30000)

    print("=" * 60)
    print("请在浏览器中扫码或手机号登录今日头条。")
    print("脚本将自动检测登录完成并保存，无需按键。")
    print("=" * 60)

    saved = False
    for i in range(POLL_TIMEOUT):
        time.sleep(1)
        try:
            cookies = context.cookies()
        except Exception:
            break

        toutiao_cookies = [c for c in cookies if "toutiao.com" in (c.get("domain") or "")]
        all_auth_names = {c["name"] for c in toutiao_cookies}
        has_required = REQUIRED_AUTH & all_auth_names
        has_nice = NICE_TO_HAVE & all_auth_names

        if i % 10 == 0 and i > 0:
            print(f"  ... waiting ({i}s, {len(toutiao_cookies)} toutiao cookies, auth: {all_auth_names & (REQUIRED_AUTH | NICE_TO_HAVE) or 'none'})")

        if has_required:
            print(f"\n[OK] 检测到登录完成！auth cookies: {has_required | has_nice}")
            TOUTIAO_AUTH_STATE.parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=str(TOUTIAO_AUTH_STATE))
            print(f"Auth state saved: {TOUTIAO_AUTH_STATE} ({len(cookies)} cookies)")
            saved = True
            break

    if saved:
        print("\n可以关闭浏览器窗口了。5秒后自动退出...")
        time.sleep(5)
    else:
        print(f"\n[WARN] {POLL_TIMEOUT}s 内未检测到登录，将保存当前 cookie 状态")
        TOUTIAO_AUTH_STATE.parent.mkdir(parents=True, exist_ok=True)
        try:
            context.storage_state(path=str(TOUTIAO_AUTH_STATE))
            print(f"Partial auth saved: {TOUTIAO_AUTH_STATE}")
        except Exception as e:
            print(f"Save failed: {e}")

    browser.close()
    print("Done!")
