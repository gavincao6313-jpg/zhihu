"""Login to zhihu + monitor live room — auto-detects login, no input() needed."""
import sys
import json
import time as _time
from pathlib import Path

AUTH_FILE = Path(__file__).resolve().parent / "zhihu_auth_state.json"
OUTPUT_FILE = Path(__file__).with_name(".last_stream_url.txt")
STATE_FILE = Path(__file__).with_name(".monitor_state.json")

LIVE_URL = sys.argv[1] if len(sys.argv) > 1 else (
    "https://www.zhihu.com/xen/training/live/room/2013265166804997499/2013265169342537989?is_hybrid=1"
)


def main():
    from playwright.sync_api import sync_playwright

    print(f"Live URL: {LIVE_URL}")
    print()

    candidates = []

    def on_request(request):
        url = request.url
        lowered = url.lower()
        patterns = [".m3u8", ".mpd", ".flv", ".mp4", "live-stream", "playlist",
                     "vzuu.com", "vdn", "pull-flv", "pull-hls", "rtmp"]
        if any(p in lowered for p in patterns):
            ext_block = [".jpg", ".jpeg", ".png", ".gif", ".webp", ".css", ".js", ".woff", ".svg"]
            if not any(e in lowered for e in ext_block):
                candidates.append((url, request.resource_type))
                print(f"  [MEDIA] {url[:200]}")

    api_candidates = []

    def on_response(response):
        url = response.url
        if response.status == 200 and response.request.resource_type in ("xhr", "fetch"):
            if any(k in url for k in ("play_url", "stream", "live", "player", "pull", "get_live", "play")):
                try:
                    body = response.text()
                    if len(body) < 50000:
                        api_candidates.append({"url": url, "body": body[:2000]})
                        print(f"  [API] {url}: {body[:300]}")
                except Exception:
                    pass

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--no-sandbox",
                "--disable-infobars",
            ],
        )

        # Try loading saved auth first
        storage_state = str(AUTH_FILE) if AUTH_FILE.exists() else None
        if storage_state:
            print(f"Using saved auth: {AUTH_FILE}")

        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            locale="zh-CN",
            storage_state=storage_state,
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
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
            """
        )
        page.on("request", on_request)
        page.on("response", on_response)

        # Step 1: Navigate to live room
        print("Step 1: Opening live room...")
        page.goto(LIVE_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        current_url = page.url

        # Step 2: If redirected to login, wait for user to log in
        if any(k in current_url.lower() for k in ("signin", "login")):
            print()
            print("=" * 50)
            print("Please log in now (QR code or password)")
            print("Script will auto-detect when login completes...")
            print("=" * 50)
            print()

            # Auto-poll for login success — check URL, title, and cookies
            logged_in = False
            for i in range(120):
                _time.sleep(2)
                try:
                    cur = page.url
                    page_title = page.title()
                    cookies = context.cookies()
                    has_session = any(
                        c.get("name") in ("SESSIONID", "z_c0", "d_c0") and c.get("value")
                        for c in cookies
                    )
                except Exception:
                    continue

                # Login detected if: URL no longer on signin/login, OR we see live content, OR zhihu cookies present
                url_ok = "signin" not in cur.lower() and "login" not in cur.lower()
                title_ok = page_title and "登录" not in page_title

                if (url_ok and title_ok) or has_session:
                    logged_in = True
                    print(f"Login detected! URL: {cur[:120]}, title: {page_title[:50]}")
                    # If URL is zhihu home (not live room), navigate to live
                    if "xen/training/live" not in cur:
                        print("  Redirecting to live room...")
                        page.goto(LIVE_URL, wait_until="domcontentloaded", timeout=30000)
                        page.wait_for_timeout(3000)
                    break
                if i % 15 == 0 and i > 0:
                    print(f"  Waiting for login... ({i*2}s elapsed, url_ok={url_ok}, title_ok={title_ok}, has_session={has_session})")

            if not logged_in:
                print("Timeout waiting for login. Please re-run.")
                browser.close()
                return

            # Save auth state
            AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=str(AUTH_FILE))
            print(f"Auth saved: {AUTH_FILE}")

            # Navigate to live room
            page.goto(LIVE_URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

        current_url = page.url
        title = page.title()
        body_text = page.evaluate("() => document.body.innerText")

        print(f"\nURL:   {current_url[:150]}")
        print(f"Title: {title}")

        if "等待老师" in body_text:
            print("\n*** Teacher hasn't started yet — monitoring every 30s ***")
            print("(Leave this running, will auto-detect when stream starts)\n")
        elif any(m in body_text for m in ("直播已结束", "直播结束")):
            print("\n*** Live has ended ***")
        else:
            print("\n*** Stream may be active ***")

        # Try to activate video
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

        # Poll for stream
        attempt = 0
        max_attempts = 120
        try:
            while attempt < max_attempts:
                attempt += 1
                page.wait_for_timeout(30000)

                try:
                    body = page.evaluate("() => document.body.innerText")
                except Exception:
                    body = ""

                try:
                    videos = page.evaluate(
                        """() => Array.from(document.querySelectorAll('video')).map(v => ({
                            src: v.src || v.currentSrc,
                            ready: v.readyState,
                            w: v.videoWidth,
                            h: v.videoHeight,
                        }))"""
                    )
                except Exception:
                    videos = []

                active = [v for v in videos if v.get("src") and v.get("w", 0) > 0]
                print(f"[{attempt:3d}] videos={len(videos)} active={len(active)} media={len(candidates)}")

                if active:
                    for v in active:
                        print(f"  Video: {v['src'][:200]}")
                        candidates.append((v["src"], "video-element"))

                if candidates:
                    print("\n*** STREAM FOUND! ***")
                    break

                if api_candidates and attempt % 4 == 0:
                    STATE_FILE.write_text(
                        json.dumps(api_candidates, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    # Scan API responses for stream URLs
                    for ac in api_candidates:
                        for keyword in [".m3u8", ".flv", "rtmp://", "pull.", "play_url"]:
                            if keyword in ac["body"]:
                                # Try to extract URL from JSON
                                body = ac["body"]
                                print(f"  API contains '{keyword}' in: {ac['url']}")
                                print(f"  Body excerpt: {body[:500]}")
                                break

                ended = ["直播已结束", "直播结束", "直播已暂停"]
                if any(m in body for m in ended):
                    print("\n*** Live ended ***")
                    break

                if "等待老师" in body and attempt % 5 == 0:
                    print(f"  Still waiting for teacher...")

        except KeyboardInterrupt:
            print("\nInterrupted.")

        # Save results
        if candidates:
            stream_url = candidates[0][0]
            OUTPUT_FILE.write_text(stream_url, encoding="utf-8")
            print(f"\nStream URL saved: {OUTPUT_FILE}")
            print(f"URL: {stream_url[:300]}")
        else:
            print(f"\nNo stream URL after {attempt} attempts.")
            if api_candidates:
                STATE_FILE.write_text(
                    json.dumps(api_candidates, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                print(f"API responses saved: {STATE_FILE}")

        browser.close()


if __name__ == "__main__":
    main()
