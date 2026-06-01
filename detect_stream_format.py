"""Quick script: use saved auth to inspect how zhihu delivers live video."""
import json
import time
from pathlib import Path

AUTH_FILE = Path(__file__).resolve().parent / "zhihu_auth_state.json"
LIVE_URL = "https://www.zhihu.com/xen/training/live/room/2013265166804997499/2013265169342537989?is_hybrid=1"


def main():
    from playwright.sync_api import sync_playwright

    captured = []

    def on_request(request):
        url = request.url
        rtype = request.resource_type
        # Capture ALL requests for analysis — not just media patterns
        if rtype in ("media", "websocket", "xhr", "fetch"):
            captured.append({
                "type": rtype,
                "url": url[:300],
                "method": request.method,
            })
            print(f"  [{rtype}] {url[:200]}")

    def on_response(response):
        url = response.url
        if response.request.resource_type in ("xhr", "fetch"):
            # Look for stream-related API responses
            for kw in ("play", "stream", "live", "pull", "room", "get_live", "push_url", "rtmp", "flv", "m3u8", "rtc", "webrtc"):
                if kw in url.lower():
                    try:
                        body = response.text()
                        if 0 < len(body) < 10000:
                            print(f"\n  [API RESP] {url}")
                            print(f"  Body: {body[:800]}")
                            captured.append({
                                "type": "api_response",
                                "url": url[:300],
                                "body": body,
                            })
                    except Exception:
                        pass

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--no-sandbox",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            locale="zh-CN",
            storage_state=str(AUTH_FILE) if AUTH_FILE.exists() else None,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            window.chrome = { runtime: {} };
            """
        )
        page.on("request", on_request)
        page.on("response", on_response)

        print("Opening live room...\n")
        page.goto(LIVE_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)

        print(f"\nURL: {page.url[:200]}")
        print(f"Title: {page.title()}")

        # Wait for video element to appear
        print("\nWaiting for video to load (15s)...")
        page.wait_for_timeout(15000)

        # Inspect all video elements
        video_info = page.evaluate(
            """() => {
              const videos = document.querySelectorAll('video');
              return Array.from(videos).map(v => ({
                src: v.src || '',
                currentSrc: v.currentSrc || '',
                readyState: v.readyState,
                networkState: v.networkState,
                videoWidth: v.videoWidth,
                videoHeight: v.videoHeight,
                paused: v.paused,
                duration: v.duration,
                error: v.error ? v.error.message : null,
                poster: v.poster || '',
              }));
            }"""
        )
        print(f"\nVideo elements: {len(video_info)}")
        for i, vi in enumerate(video_info):
            print(f"\n  video[{i}]:")
            for k, v in vi.items():
                if v or k in ("src", "currentSrc"):
                    print(f"    {k}: {v}")

        # Check for iframes (might embed CC player)
        iframes = page.evaluate(
            """() => {
              return Array.from(document.querySelectorAll('iframe')).map(f => ({
                src: f.src || '',
                id: f.id || '',
                className: f.className || '',
              }));
            }"""
        )
        print(f"\nIframes: {len(iframes)}")
        for f in iframes:
            print(f"  id={f['id'][:60]} src={f['src'][:200]}")

        # Check for any <object> or <embed>
        objects = page.evaluate(
            """() => Array.from(document.querySelectorAll('object, embed')).map(e => ({
                tag: e.tagName,
                src: e.src || e.data || '',
                type: e.type || '',
            }))"""
        )
        if objects:
            print(f"\nObjects/Embeds: {len(objects)}")
            for o in objects:
                print(f"  {o}")

        # Check all WebSocket connections
        ws_urls = page.evaluate(
            """() => {
              // Can't directly list WebSockets, but check if any global player has URLs
              const results = [];
              for (const key of Object.keys(window)) {
                try {
                  const val = window[key];
                  if (val && typeof val === 'object' && val.src) {
                    if (typeof val.src === 'string' && val.src.length > 0) {
                      results.push({key, src: val.src.toString().substring(0, 200)});
                    }
                  }
                } catch(e) {}
              }
              return results;
            }"""
        )
        if ws_urls:
            print(f"\nGlobal objects with src:")
            for w in ws_urls:
                print(f"  {w}")

        # Check for CC player specifically
        cc_info = page.evaluate(
            """() => {
              const results = {};
              // Check common CC/DocCloud player globals
              for (const key of ['DOCCTALK', 'CC', 'DocCloud', 'Polyv', 'polyv', 'player', 'livePlayer', 'DwLive']) {
                if (window[key]) {
                  results[key] = typeof window[key];
                }
              }
              return results;
            }"""
        )
        print(f"\nPlayer globals: {cc_info if cc_info else 'none'}")

        print(f"\n\nTotal captured requests: {len(captured)}")
        # Save for analysis
        out = Path(__file__).with_name(".stream_detection.json")
        out.write_text(json.dumps(captured, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Saved to: {out}")

        print("\nPress Enter to close...")
        browser.close()


if __name__ == "__main__":
    main()
