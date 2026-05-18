"""Open browser, login to zhihu with anti-detection, save storage state."""
import sys
from pathlib import Path

AUTH_FILE = Path(__file__).resolve().parent / "zhihu_auth_state.json"
LIVE_URL = "https://www.zhihu.com/xen/training/live/room/2013265166804997499/2013265169342537989?is_hybrid=1"


def main():
    from playwright.sync_api import sync_playwright

    print("Opening browser with anti-detection measures...")
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--no-sandbox",
                "--disable-infobars",
                "--disable-dev-shm-usage",
                "--disable-setuid-sandbox",
                "--disable-web-security",
                "--disable-features=BlockInsecurePrivateNetworkRequests",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            locale="zh-CN",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
            ),
        )

        # Remove automation traces
        page = context.new_page()
        page.add_init_script(
            """
            // Remove webdriver detection
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            // Remove chrome runtime
            window.chrome = { runtime: {} };
            // Remove plugins detection
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
            """
        )

        print("Navigating to zhihu signin...")
        page.goto("https://www.zhihu.com/signin", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)

        print(f"Current URL: {page.url[:150]}")
        print()
        print("=" * 50)
        print("Please log in now in the browser window.")
        print("After login succeeds, press Enter here...")
        print("=" * 50)
        input()

        # Verify login
        page.goto(LIVE_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        current_url = page.url
        print(f"\nLive room URL: {current_url[:150]}")
        print(f"Page title: {page.title()}")

        if any(k in current_url.lower() for k in ("signin", "login")):
            print("\nWARNING: Still redirected to login. Try again.")
            browser.close()
            return

        # Save auth state
        AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(AUTH_FILE))
        print(f"\nAuth state saved to: {AUTH_FILE}")
        browser.close()

    print("Done. You can now use --playwright-storage-state zhihu_auth_state.json")


if __name__ == "__main__":
    main()
