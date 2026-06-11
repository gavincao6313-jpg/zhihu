"""Test updated yt-dlp with Toutiao original URLs."""
import sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "scripts"))
from toutiao_common import storage_state_to_netscape_cookie_file, TOUTIAO_AUTH_STATE
import yt_dlp

urls = [
    "https://www.toutiao.com/item/7640124142305559094/",
    "https://toutiao.com/group/7649305952604144128/",
    "https://www.toutiao.com/video/7648192518505136168/",
]
cookie_file = storage_state_to_netscape_cookie_file(TOUTIAO_AUTH_STATE)
try:
    for url in urls:
        print(f"\n=== {url} ===")
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "cookiefile": str(cookie_file)}) as ydl:
                info = ydl.extract_info(url, download=False)
                title = info.get("title", "?")[:80]
                n_formats = len(info.get("formats", []))
                dur = info.get("duration", "?")
                print(f"  OK: {title} | formats: {n_formats} | duration: {dur}s")
        except Exception as e:
            print(f"  FAIL: {type(e).__name__}: {e}")
finally:
    os.unlink(str(cookie_file))
