"""Test yt-dlp with ixigua-mobile URL directly."""
import sys, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "scripts"))

from toutiao_common import storage_state_to_netscape_cookie_file, TOUTIAO_AUTH_STATE

try:
    import yt_dlp
except ImportError:
    print("yt-dlp not installed")
    sys.exit(1)

# Test a few ixigua-mobile URLs
test_ids = [
    "7640124142305559094",   # Loop Engineering
    "7648192518505136168",   # AI前沿技术
    "7649305952604144128",   # Claude Code
]

cookie_file = storage_state_to_netscape_cookie_file(TOUTIAO_AUTH_STATE)

try:
    for vid in test_ids:
        url = f"https://m.ixigua.com/video/{vid}?wid_try=1"
        print(f"\nTesting: {url}")
        ydl_opts = {
            "quiet": False,
            "cookiefile": str(cookie_file),
            "format": "bv*+ba/best",
            "merge_output_format": "mp4",
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                formats = info.get("formats", [])
                print(f"  Title: {info.get('title', '?')[:60]}")
                print(f"  Duration: {info.get('duration', '?')}s")
                print(f"  Formats found: {len(formats)}")
                for f in formats[:3]:
                    print(f"    {f.get('format_id')} | {f.get('ext')} | {f.get('resolution', '?')} | {f.get('filesize', '?')}")
        except Exception as e:
            print(f"  FAILED: {e}")
finally:
    try:
        os.unlink(str(cookie_file))
    except Exception:
        pass
