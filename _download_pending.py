"""Download only truly pending items (status='pending', not 'skip' or 'done')."""
import json, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))

from toutiao_common import (
    TOUTIAO_AUTH_STATE, TOUTIAO_MANIFEST, TOUTIAO_VIDEO_DIR,
    ensure_dirs, now_iso, save_manifest, storage_state_to_netscape_cookie_file,
)

try:
    import yt_dlp
except ImportError:
    print("yt-dlp not installed")
    sys.exit(1)

manifest = json.load(open(TOUTIAO_MANIFEST, "r", encoding="utf-8"))
items = manifest.get("items", {})

# Select only truly pending items (not done, not skip)
pending = [(k, v) for k, v in items.items() if v.get("download_status") == "pending"]
print(f"Truly pending: {len(pending)}")
for k, v in pending[:5]:
    print(f"  {k} | {v['detail_url']}")
if len(pending) > 5:
    print(f"  ... and {len(pending) - 5} more")

if not pending:
    print("Nothing to download!")
    sys.exit(0)

ensure_dirs()
TOUTIAO_VIDEO_DIR.mkdir(parents=True, exist_ok=True)
cookie_file = storage_state_to_netscape_cookie_file(TOUTIAO_AUTH_STATE)

try:
    ok_count = 0
    fail_count = 0
    for idx, (k, record) in enumerate(pending, 1):
        url = record["detail_url"]
        print(f"\n[{idx}/{len(pending)}] {k}")
        try:
            ydl_opts = {
                "outtmpl": str(TOUTIAO_VIDEO_DIR / f"{k}.%(ext)s"),
                "quiet": True,
                "no_warnings": True,
                "cookiefile": str(cookie_file),
                "format": "bv*+ba/best",
                "merge_output_format": "mp4",
                "noplaylist": True,
                "retries": 3,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = Path(ydl.prepare_filename(info))
            # Find actual output file
            candidates = sorted(TOUTIAO_VIDEO_DIR.glob(f"{k}.*"), key=lambda p: p.stat().st_mtime, reverse=True)
            if candidates:
                out_path = candidates[0]
                record["download_status"] = "done"
                record["local_path"] = str(out_path)
                record["downloaded_at"] = now_iso()
                record["download_method"] = "ytdlp"
                record["last_error"] = ""
                dur = info.get("duration", "?")
                size_mb = out_path.stat().st_size / 1024 / 1024
                print(f"  OK: {out_path.name} ({size_mb:.1f}MB, {dur}s)")
                ok_count += 1
            else:
                raise RuntimeError("no output file found")
        except Exception as e:
            record["download_status"] = "failed"
            record["last_error"] = str(e)[:300]
            print(f"  FAIL: {str(e)[:150]}")
            fail_count += 1

        save_manifest(manifest, TOUTIAO_MANIFEST)

    print(f"\n=== Done: {ok_count} OK, {fail_count} failed ===")
finally:
    try:
        os.unlink(str(cookie_file))
    except Exception:
        pass
