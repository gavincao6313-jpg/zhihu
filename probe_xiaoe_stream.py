"""Non-interactive 小鹅通 live stream probe.

Usage: python probe_xiaoe_stream.py <page_url> <auth_state_json>

Exits 0 and prints "M3U8_URL=<url>" when a valid m3u8 stream is found.
Exits 1 on timeout or failure (nothing printed to stdout).
"""
import sys
import time
from playwright.sync_api import sync_playwright

_MEDIA_KEYWORDS = (
    ".m3u8",
    "liveplay",
    "myqcloud",
    "confusion",
    "pull",
    "get_live_url",
    "stream_url",
)

_TIMEOUT_S = 45


def _is_m3u8_url(url: str) -> bool:
    low = url.lower()
    return ".m3u8" in low and any(k in low for k in _MEDIA_KEYWORDS)


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: probe_xiaoe_stream.py <page_url> <auth_state_json>", file=sys.stderr)
        return 1

    page_url = sys.argv[1]
    auth_file = sys.argv[2]
    found: list[str] = []

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

        def on_request(request: object) -> None:
            url = request.url  # type: ignore[attr-defined]
            if _is_m3u8_url(url):
                found.append(url)

        page.on("request", on_request)

        try:
            page.goto(page_url, wait_until="domcontentloaded", timeout=30_000)
        except Exception as exc:
            print(f"[probe] goto error: {exc}", file=sys.stderr)

        deadline = time.time() + _TIMEOUT_S
        last_trigger = 0.0
        while time.time() < deadline:
            if found:
                break
            # Trigger video playback every 3s
            if time.time() - last_trigger >= 3.0:
                try:
                    page.evaluate("""
                        (function() {
                            var btns = document.querySelectorAll('button, .play-btn, .video-play, [class*=play]');
                            for (var i = 0; i < btns.length; i++) {
                                if (btns[i].offsetParent !== null) btns[i].click();
                            }
                            var vids = document.querySelectorAll('video');
                            for (var j = 0; j < vids.length; j++) {
                                vids[j].muted = true;
                                vids[j].play().catch(function(){});
                            }
                        })()
                    """)
                    last_trigger = time.time()
                except Exception:
                    pass
            time.sleep(0.5)

        browser.close()

    if found:
        # Prefer URLs with time= auth param (小鹅通 signed URLs)
        best = next((u for u in found if "time=" in u), found[0])
        print(f"M3U8_URL={best}")
        return 0

    print("[probe] no m3u8 found within timeout", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
