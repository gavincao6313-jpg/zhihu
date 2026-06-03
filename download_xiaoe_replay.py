"""Download xiaoe replay: intercept m3u8 via Playwright, download all TS, concat to MP4."""
from playwright.sync_api import sync_playwright
import requests
import subprocess
import time
import sys
import os
from pathlib import Path

auth_file = r"d:\zhihu\zhihu_file\zhihu_auth_state_xiaoe.json"
# Try both the replay/lookback URL and the regular alive URL
urls_to_try = [
    "https://appzl5apwz41977.h5.xiaoeknow.com/v3/course/alive/l_6a1c5fe3e4b0694c5bcddcbc?app_id=appzl5apwz41977&pro_id=p_62ee3208e4b0eca59c1f854d&type=2",
    "https://appzl5apwz41977.h5.xet.pomoho.com/v4/course/alive/l_6a1c5fe3e4b0694c5bcddcbc?type=2&resource_type=4&resource_id=l_6a1c5fe3e4b0694c5bcddcbc&app_id=appzl5apwz41977&pro_id=p_62ee3208e4b0eca59c1f854d&conduit_id=p_62ee3208e4b0eca59c1f854d&conduit_type=live_group",
]

found_m3u8 = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(storage_state=auth_file)
    page = context.new_page()

    page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: function() { return false; } });
        window.chrome = { runtime: {} };
    """)

    def on_request(request):
        url = request.url
        if ".m3u8" in url.lower():
            found_m3u8.append(url)
            print(f"[M3U8] {url[:250]}")

    page.on("request", on_request)

    for url in urls_to_try:
        if found_m3u8:
            break
        print(f"Trying: {url[:100]}...")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            print(f"  Page: {page.url[:150]}")
        except Exception as e:
            print(f"  Error: {e}")
            continue

        # Trigger video playback
        try:
            page.evaluate("""
                (function() {
                    var videos = document.querySelectorAll('video');
                    for (var i = 0; i < videos.length; i++) {
                        videos[i].muted = true;
                        videos[i].play().catch(function(){});
                    }
                })()
            """)
        except:
            pass

        # Wait for video to start and m3u8 to be intercepted
        for _ in range(15):
            if found_m3u8:
                break
            time.sleep(1)

    browser.close()

if not found_m3u8:
    print("ERROR: No m3u8 URL found. The replay might not be available yet.")
    print("Try again later or check if lookback is enabled.")
    sys.exit(1)

m3u8_url = found_m3u8[0]
print(f"\nM3U8 URL: {m3u8_url[:200]}")

# Download the m3u8 playlist
import json
with open(auth_file) as f:
    auth = json.load(f)
cookies = {c["name"]: c["value"] for c in auth.get("cookies", [])}

# Save m3u8 URL for later use
Path(r"d:\zhihu\zhihu_file\.xiaoe_replay_m3u8").write_text(m3u8_url)
print("M3U8 URL saved to .xiaoe_replay_m3u8")

# Download with ffmpeg directly
output = r"d:\zhihu\zhihu_file\Videos\replay-xiaoe-20260603.mp4"
print(f"\nDownloading replay with ffmpeg -> {output}")
cmd = [
    "ffmpeg", "-y",
    "-headers", f"Referer: https://appzl5apwz41977.h5.xiaoeknow.com/",
    "-i", m3u8_url,
    "-c", "copy",
    "-bsf:a", "aac_adtstoasc",
    output
]
print(f"Command: {' '.join(cmd)}")
result = subprocess.run(cmd, capture_output=True, text=True)
print(result.stdout[-500:] if result.stdout else "")
print(result.stderr[-500:] if result.stderr else "")
print(f"\nExit code: {result.returncode}")
if result.returncode == 0:
    size_mb = os.path.getsize(output) / 1e6
    print(f"Downloaded: {size_mb:.0f} MB -> {output}")
else:
    print("ffmpeg download failed. You may need to use a proxy.")
