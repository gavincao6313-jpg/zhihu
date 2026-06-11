"""Mark known-bad items as skip so downloader doesn't waste time on them."""
import json
from pathlib import Path
from datetime import datetime

manifest_path = Path("cache/toutiao/manifest.json")
m = json.load(open(manifest_path, "r", encoding="utf-8"))

now = datetime.now().isoformat(timespec="seconds")

skipped = 0
for k, v in m["items"].items():
    if v.get("download_status") == "done":
        continue
    url = v.get("detail_url", "")
    # /video/ URLs: yt-dlp toutiao extractor broken, will never work
    if "/video/" in url:
        v["download_status"] = "skip"
        v["last_error"] = "yt-dlp toutiao /video/ extractor broken (2026-06), need manual download"
        skipped += 1
        print(f"SKIP (video): {k}")
    # sslocal:// URLs: text posts, not videos
    elif "sslocal://" in url:
        v["download_status"] = "skip"
        v["last_error"] = "sslocal:// URL - text post, not a video"
        skipped += 1
        print(f"SKIP (sslocal): {k}")

m["updated_at"] = now
json.dump(m, open(manifest_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

pending = sum(1 for v in m["items"].values() if v.get("download_status") != "done" and v.get("download_status") != "skip")
print(f"\nSkipped: {skipped}, Remaining pending: {pending}")

# List remaining pending
for k, v in m["items"].items():
    if v.get("download_status") not in ("done", "skip"):
        print(f"  PENDING: {k} | {v['detail_url']}")
