"""Probe xiaoe H5 page for media stream URLs."""
from playwright.sync_api import sync_playwright
import sys, time, json

# Try the H5 URL instead of the xet.pomoho.com one
url = "https://appzl5apwz41977.h5.xiaoeknow.com/v2/course/alive/l_6a1c5fe3e4b0694c5bcddcbc?app_id=appzl5apwz41977&pro_id=p_62ee3208e4b0eca59c1f854d&type=2"
auth_file = r"d:\zhihu\zhihu_file\zhihu_auth_state_xiaoe.json"

requests_log = []
media_log = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
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
        requests_log.append(req_url)
        low = req_url.lower()
        if any(k in low for k in [".m3u8", ".flv", ".mp4", ".ts", "liveplay", "myqcloud", "confusion", "vod", "rtmp", "hls", "pull", "stream", "play", "get_live"]):
            media_log.append(f"[REQ] {req_url[:300]}")

    def on_response(response):
        resp_url = response.url
        low = resp_url.lower()
        if any(k in low for k in [".m3u8", ".flv", "liveplay", "myqcloud", "confusion", "vod", "rtmp", "hls", "pull", "stream", "get_live"]):
            try:
                body = response.text()[:500]
            except:
                body = "(binary)"
            media_log.append(f"[RESP] {response.status} {resp_url[:200]}")
            media_log.append(f"  Body: {body[:300]}")

    page.on("request", on_request)
    page.on("response", on_response)

    print(f"Navigating to: {url[:100]}...")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        print(f"Page URL: {page.url[:200]}")
        print(f"Title: {page.title()}")
    except Exception as e:
        print(f"Goto error: {e}")

    try:
        page.evaluate("""
            (function() {
                for (var i = 0; i < document.querySelectorAll('video').length; i++) {
                    var v = document.querySelectorAll('video')[i];
                    v.muted = true;
                    v.play().catch(function(){});
                }
            })()
        """)
    except:
        pass

    print("Waiting 15s...")
    time.sleep(15)

    print(f"\nTotal requests: {len(requests_log)}")
    print(f"Media-related ({len(media_log)}):")
    for m in media_log:
        print(f"  {m}")

    if not media_log:
        print("\nALL requests:")
        for r in requests_log:
            print(f"  {r[:250]}")

    browser.close()
