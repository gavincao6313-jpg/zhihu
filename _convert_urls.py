"""Convert toutiao /item/ and /group/ URLs to /video/ format, unskip items."""
import json
from pathlib import Path
from datetime import datetime
import re

manifest_path = Path("cache/toutiao/manifest.json")
m = json.load(open(manifest_path, "r", encoding="utf-8"))
now = datetime.now().isoformat(timespec="seconds")

converted = 0
unskipped = 0
for k, v in m["items"].items():
    url = v.get("detail_url", "")
    # Extract numeric ID from any URL format
    id_match = re.search(r"/(\d{10,})[/?]?", url)
    if not id_match:
        continue
    vid = id_match.group(1)
    new_url = f"https://www.toutiao.com/video/{vid}/"

    if url != new_url and "/video/" not in url:
        old_url = url
        v["detail_url"] = new_url
        print(f"CONVERT: {k}\n  OLD: {old_url}\n  NEW: {new_url}")
        converted += 1

    # Unskip items that were marked skip because of /video/ extractor
    if v.get("download_status") == "skip" and "yt-dlp toutiao" in (v.get("last_error") or ""):
        v["download_status"] = "pending"
        v["last_error"] = ""
        unskipped += 1
        print(f"UNSKIP: {k}")

m["updated_at"] = now
json.dump(m, open(manifest_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

pending = sum(1 for v in m["items"].values() if v.get("download_status") not in ("done", "skip"))
print(f"\nConverted: {converted}, Unskipped: {unskipped}, Remaining pending: {pending}")
