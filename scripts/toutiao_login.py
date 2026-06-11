from __future__ import annotations

import argparse
from pathlib import Path

from toutiao_common import (
    ANTI_DETECTION_ARGS,
    DEFAULT_TOUTIAO_HOME_URL,
    TOUTIAO_AUTH_STATE,
    build_playwright_context,
    ensure_dirs,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Login to Toutiao and save Playwright storage state")
    parser.add_argument("--auth-state", type=Path, default=TOUTIAO_AUTH_STATE)
    parser.add_argument("--login-url", default=DEFAULT_TOUTIAO_HOME_URL)
    args = parser.parse_args()

    ensure_dirs()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("playwright 未安装。请先 pip install playwright && playwright install chromium") from exc

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=ANTI_DETECTION_ARGS)
        context = build_playwright_context(browser)
        page = context.new_page()
        page.goto(args.login_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)

        print("=" * 60)
        print("请在打开的浏览器里登录今日头条。")
        print("登录完成后回到终端按 Enter，脚本会保存登录态。")
        print("=" * 60)
        input()

        page.goto(args.login_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        print(f"Current URL : {page.url}")
        print(f"Page title  : {page.title()}")

        args.auth_state.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(args.auth_state))
        print(f"Auth state saved: {args.auth_state}")

        import json
        state = json.loads(args.auth_state.read_text(encoding="utf-8"))
        all_cookies = state.get("cookies", [])
        toutiao_domains = ("toutiao.com", "bytedance.com", "snssdk.com")
        toutiao_cookies = [c for c in all_cookies if any(d in (c.get("domain") or "") for d in toutiao_domains)]
        auth_names = ("sso_uid_tt", "toutiao_sso_user", "passport_auth_status", "sessionid")
        auth_cookies = [c for c in toutiao_cookies if c.get("name") in auth_names]
        if auth_cookies:
            print(f"[OK] 登录成功，已捕获 {len(auth_cookies)} 个认证 cookie：{[c['name'] for c in auth_cookies]}")
        else:
            print(f"[WARN] 未找到头条认证 cookie（共保存 {len(toutiao_cookies)} 个字节系 cookie）")
            print("       请确认浏览器内已完成登录，然后重新运行本脚本。")

        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
