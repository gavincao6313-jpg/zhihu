"""Headed browser probe: show the xiaoe page and capture ALL m3u8/stream URLs."""
from playwright.sync_api import sync_playwright
import time, json, re

auth_file = r"d:\zhihu\zhihu_file\zhihu_auth_state_xiaoe.json"
url = "https://appzl5apwz41977.h5.xiaoeknow.com/v2/course/alive/l_6a1c5fe3e4b0694c5bcddcbc?app_id=appzl5apwz41977&pro_id=p_62ee3208e4b0eca59c1f854d&type=2"

found_urls = set()

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context(
        storage_state=auth_file,
        viewport={"width": 1280, "height": 720},
    )
    page = context.new_page()

    page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => false });
        window.chrome = { runtime: {} };
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    """)

    def on_request(request):
        req_url = request.url
        low = req_url.lower()
        if any(k in low for k in [".m3u8", ".flv", ".ts", "liveplay", "myqcloud", "confusion", "vod", "pull", "get_live_url", "stream_url"]):
            found_urls.add(req_url)
            print(f"[MEDIA REQ] {req_url[:300]}")

    def on_response(response):
        resp_url = response.url
        low = resp_url.lower()
        if any(k in low for k in [".m3u8", "liveplay", "myqcloud", "confusion", "pull", "get_live_url"]):
            found_urls.add(resp_url)
            try:
                body = response.text()[:1000]
                print(f"[MEDIA RESP {response.status}] {resp_url[:200]}")
                print(f"  Body: {body[:500]}")
            except:
                print(f"[MEDIA RESP {response.status}] {resp_url[:200]}")

    page.on("request", on_request)
    page.on("response", on_response)

    print("Opening headed browser...")
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    print(f"Page: {page.url[:200]}")
    print(f"Title: {page.title()}")
    print()

    # Wait for the page to fully load and video to start
    print("Waiting for video to load (30s max). Watch the browser window...")
    for i in range(30):
        time.sleep(1)
        # Try to click play buttons
        if i == 3:
            try:
                page.evaluate("""
                    (function() {
                        var btns = document.querySelectorAll('button, .play-btn, .video-play, [class*=play]');
                        for (var i = 0; i < btns.length; i++) {
                            if (btns[i].offsetParent !== null) btns[i].click();
                        }
                        for (var j = 0; j < document.querySelectorAll('video').length; j++) {
                            var v = document.querySelectorAll('video')[j];
                            v.muted = true;
                            v.play().catch(function(){});
                        }
                    })()
                """)
            except:
                pass

    print(f"\n=== RESULTS ===")
    if found_urls:
        print(f"Found {len(found_urls)} media URLs:")
        for u in sorted(found_urls):
            print(f"  {u}")

        # Save for pipeline use
        m3u8_urls = [u for u in found_urls if '.m3u8' in u.lower()]
        if m3u8_urls:
            with open(r"d:\zhihu\zhihu_file\.xiaoe_m3u8_url", "w") as f:
                f.write(m3u8_urls[0])
            print(f"\nM3U8 URL saved to .xiaoe_m3u8_url")
    else:
        print("NO media URLs found. The page might use WebRTC or a proprietary player.")

    print("\nClose the browser window to continue...")
    input("Press Enter after closing browser...")
    browser.close()
