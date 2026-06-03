"""Quick probe: navigate to xiaoe page and dump all network requests."""
from playwright.sync_api import sync_playwright
import sys, time, json

url = sys.argv[1] if len(sys.argv) > 1 else "https://appzl5apwz41977.h5.xet.pomoho.com/v4/course/alive/l_6a1c5fe3e4b0694c5bcddcbc?type=2&resource_type=4&resource_id=l_6a1c5fe3e4b0694c5bcddcbc&app_id=appzl5apwz41977&pro_id=p_62ee3208e4b0eca59c1f854d&conduit_id=p_62ee3208e4b0eca59c1f854d&conduit_type=live_group"
auth_file = r"d:\zhihu\zhihu_file\zhihu_auth_state_xiaoe.json"

requests_log = []
media_log = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(storage_state=auth_file)
    page = context.new_page()

    def on_request(request):
        req_url = request.url
        requests_log.append(req_url)
        low = req_url.lower()
        if any(k in low for k in [".m3u8", ".flv", ".mp4", ".ts", "liveplay", "myqcloud", "confusion", "vod", "rtmp", "webrtc", "stream", "hls", "pull", "play"]):
            media_log.append(f"[REQ] {req_url[:300]}")

    def on_response(response):
        resp_url = response.url
        low = resp_url.lower()
        if any(k in low for k in [".m3u8", ".flv", "liveplay", "myqcloud", "confusion", "vod", "rtmp", "hls", "pull", "stream"]):
            media_log.append(f"[RESP] {response.status} {resp_url[:300]}")

    page.on("request", on_request)
    page.on("response", on_response)

    print(f"Navigating to: {url[:100]}...")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        print(f"Page URL after load: {page.url[:200]}")
        print(f"Page title: {page.title()}")
    except Exception as e:
        print(f"Goto error: {e}")

    # Trigger video play
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
        print("Video play triggered")
    except Exception as e:
        print(f"Video trigger error: {e}")

    print("Waiting 20s for media requests...")
    time.sleep(20)

    print(f"\nTotal requests: {len(requests_log)}")
    print(f"Media-related ({len(media_log)}):")
    for m in media_log:
        print(f"  {m}")

    if not media_log:
        print("\nALL requests:")
        for r in requests_log:
            print(f"  {r[:250]}")

    browser.close()
