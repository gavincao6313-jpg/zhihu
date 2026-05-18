"""Open headed browser, let user log in to zhihu, save storage state for stream processing."""
import sys
from pathlib import Path

SAVE_PATH = Path(__file__).resolve().parent / "zhihu_auth_state.json"


def main():
    from playwright.sync_api import sync_playwright

    print("Opening browser...")
    print("  1. Log in to zhihu in the browser window")
    print("  2. After login succeeds and you see the live room, come back here")
    print("  3. Press Enter in this terminal to save the auth state")
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            locale="zh-CN",
        )
        page = context.new_page()

        page.goto("https://www.zhihu.com/signin", wait_until="domcontentloaded", timeout=30000)
        print(f"Current URL: {page.url}")
        print()
        print("=" * 60)
        print("LOG IN NOW in the browser window.")
        print("When done, press Enter here to save auth state...")
        print("=" * 60)

        input()

        # Verify login succeeded
        current_url = page.url
        print(f"\nAfter login URL: {current_url}")
        if "signin" in current_url.lower() or "login" in current_url.lower():
            print("WARNING: Still on login page. Auth may not be saved correctly.")

        SAVE_PATH.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(SAVE_PATH))
        print(f"\nAuth state saved to: {SAVE_PATH}")

        # Also verify by navigating to the live room
        print("\nNavigating to live room to verify access...")
        page.goto(
            "https://www.zhihu.com/xen/training/live/room/2013265166804997499/2013265169342537989?is_hybrid=1",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        page.wait_for_timeout(3000)
        print(f"Live room URL: {page.url}")
        print(f"Page title: {page.title()}")
        if "signin" in page.url.lower() or "login" in page.url.lower():
            print("ERROR: Still redirected to login. Auth may be incomplete.")
        else:
            print("OK: Access to live room confirmed.")

        browser.close()

    print("\nDone. Auth state ready for stream processing.")
    print(f"Auth file: {SAVE_PATH}")


if __name__ == "__main__":
    main()
