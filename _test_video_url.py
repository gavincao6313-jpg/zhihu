"""Test if /video/ URL format works for all flavors."""
import sys, os, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "scripts"))
from toutiao_common import storage_state_to_netscape_cookie_file, TOUTIAO_AUTH_STATE
import yt_dlp

# Test converting /item/ and /group/ to /video/ URLs
ids_to_test = [
    "7640124142305559094",   # /item/ -> try /video/
    "7649305952604144128",   # /group/ -> try /video/
    "7648842284393382440",   # /group/
    "7648192518505136168",   # /item/ (already works as /video/)
]

cookie_file = storage_state_to_netscape_cookie_file(TOUTIAO_AUTH_STATE)
try:
    for vid in ids_to_test:
        url = f"https://www.toutiao.com/video/{vid}/"
        print(f"\n=== {url} ===")
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "cookiefile": str(cookie_file)}) as ydl:
                info = ydl.extract_info(url, download=False)
                title = info.get("title", "?")[:80]
                n_formats = len(info.get("formats", []))
                dur = info.get("duration", "?")
                print(f"  OK: {title} | formats: {n_formats} | duration: {dur}s")
        except Exception as e:
            msg = str(e)[:150]
            print(f"  FAIL: {msg}")
finally:
    os.unlink(str(cookie_file))
