"""Probe zhihu live URL — uses local Chrome profile to inherit zhihu login session."""
import sys
import time
from pathlib import Path

CHROME_PROFILE = r"C:\Users\Admin\AppData\Local\Google\Chrome\User Data"


def main():
    from playwright.sync_api import sync_playwright

    page_url = sys.argv[1] if len(sys.argv) > 1 else ""
    if not page_url:
        # Default zhihu live URL
        page_url = "https://www.zhihu.com/xen/training/live/room/2013265166804997499/2013265169342537989?is_hybrid=1"

    print(f"Target: {page_url}")
    print(f"Chrome profile: {CHROME_PROFILE}")
    print()
    print("NOTE: Close all Chrome windows before continuing!")
    print("Press Enter when Chrome is closed...")
    input()

    candidates = []

    def on_request(request):
        url = request.url
        lowered = url.lower()
        patterns = [".m3u8", ".mpd", ".flv", ".mp4", "live-stream", "playlist", "vzuu.com", "vdn", "pull-flv"]
        if any(p in lowered for p in patterns):
            ext_block = [".jpg", ".jpeg", ".png", ".gif", ".webp", ".css", ".js", ".woff"]
            if not any(e in lowered for e in ext_block):
                candidates.append((url, request.resource_type))

    def on_response(response):
        if response.status >= 300 and response.status < 400:
            loc = response.headers.get("location", "")
            if loc:
                tag = ""
                if any(k in loc.lower() for k in ("login", "signin")):
                    tag = " *** LOGIN REDIRECT ***"
                print(f"  [{response.status}] → {loc[:150]}{tag}")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            CHROME_PROFILE,
            headless=False,
            channel="chrome",
            viewport={"width": 1280, "height": 720},
            locale="zh-CN",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        page = context.new_page()
        page.on("request", on_request)
        page.on("response", on_response)

        print("\nNavigating to live room...")
        try:
            page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"Navigation error: {e}")

        page.wait_for_timeout(5000)

        current_url = page.url
        title = page.title()
        print(f"\nFinal URL: {current_url}")
        print(f"Page title: {title}")

        # Check login status
        if any(k in current_url.lower() for k in ("login", "signin")):
            print("\n*** NOT LOGGED IN ***")
            print("Log in manually in the browser window now.")
            print("After login succeeds press Enter to continue...")
            input()
            page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            current_url = page.url
            title = page.title()
            print(f"After login URL: {current_url}")
            print(f"Page title: {title}")

        # Check for video elements
        try:
            videos = page.eval_on_selector_all(
                "video",
                """els => els.map(el => ({
                    src: el.src || el.currentSrc || '',
                    ready: el.readyState,
                    paused: el.paused,
                    duration: el.duration,
                    w: el.videoWidth,
                    h: el.videoHeight,
                    error: el.error ? el.error.message : null,
                }))""",
            )
        except Exception:
            videos = []

        print(f"\nVideo elements: {len(videos)}")
        for i, v in enumerate(videos):
            for k, val in v.items():
                if val or k == "src":
                    print(f"  video[{i}].{k}: {val}")

        # Activate media
        print("\nActivating media playback...")
        try:
            page.mouse.move(640, 360)
            page.mouse.wheel(0, 500)
            page.wait_for_timeout(800)
            page.mouse.wheel(0, -500)
        except Exception:
            pass
        try:
            page.evaluate(
                """() => {
                  for (const v of document.querySelectorAll('video')) {
                    v.muted = true;
                    v.play().catch(() => {});
                  }
                }"""
            )
        except Exception:
            pass

        # Wait for media requests
        print("Waiting for media requests (15s)...")
        page.wait_for_timeout(15000)

        print(f"\nMedia candidates: {len(candidates)}")
        for url, rtype in candidates:
            print(f"  [{rtype}] {url[:250]}")

        if candidates:
            print("\nSUCCESS: Media stream URL found!")
            # Save the first candidate for use
            stream_url = candidates[0][0]
            Path(__file__).with_name(".last_stream_url.txt").write_text(stream_url, encoding="utf-8")
            print(f"Saved to: {Path(__file__).with_name('.last_stream_url.txt')}")
        else:
            print("\nNo media candidates found.")
            print("Check browser window — can you see the live stream playing?")
            print("Press Enter after inspecting...")
            input()

        context.close()


if __name__ == "__main__":
    main()
