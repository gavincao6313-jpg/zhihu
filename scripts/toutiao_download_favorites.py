from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from toutiao_common import (
    TOUTIAO_AUTH_STATE,
    TOUTIAO_MANIFEST,
    TOUTIAO_VIDEO_DIR,
    canonical_url,
    ensure_dirs,
    load_manifest,
    now_iso,
    save_manifest,
    slugify,
    storage_state_to_netscape_cookie_file,
)


def existing_local_path(record: dict) -> Path | None:
    local = record.get("local_path") or ""
    if local:
        path = Path(local)
        if path.exists() and path.stat().st_size > 0:
            return path
    return None


def download_with_ytdlp(url: str, item_id: str, output_dir: Path, auth_state: Path) -> tuple[Path, str]:
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("yt-dlp 未安装。请先 pip install yt-dlp") from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    cookie_file = storage_state_to_netscape_cookie_file(auth_state) if auth_state.exists() else None
    outtmpl = str(output_dir / f"{item_id}.%(ext)s")
    ydl_opts = {
        "outtmpl": outtmpl,
        "quiet": False,
        "no_warnings": False,
        "format": "bv*+ba/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "retries": 3,
        "fragment_retries": 3,
    }
    if cookie_file:
        ydl_opts["cookiefile"] = str(cookie_file)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = Path(ydl.prepare_filename(info))
    finally:
        if cookie_file:
            cookie_file.unlink(missing_ok=True)

    candidates = sorted(output_dir.glob(f"{item_id}.*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if candidates:
        return candidates[0], "ytdlp"
    if filename.exists():
        return filename, "ytdlp"
    raise RuntimeError("yt-dlp completed but no output file was found")


def download_with_playwright_capture(url: str, item_id: str, output_dir: Path,
                                     auth_state: Path, timeout_ms: int) -> tuple[Path, str]:
    from stream_extractors import extract_stream

    output_dir.mkdir(parents=True, exist_ok=True)
    stream = extract_stream(
        url,
        extractor="playwright",
        storage_state=str(auth_state) if auth_state.exists() else "",
        timeout_ms=timeout_ms,
        wait_seconds=8.0,
    )
    suffix = ".mp4"
    if stream.media_type == "hls":
        suffix = ".mp4"
    elif stream.media_type in ("flv", "mp4"):
        suffix = f".{stream.media_type}"
    output_path = output_dir / f"{item_id}{suffix}"
    headers_text = "".join(f"{key}: {value}\r\n" for key, value in stream.headers.items())
    cmd = ["ffmpeg", "-y"]
    if headers_text:
        cmd += ["-headers", headers_text]
    cmd += ["-i", stream.url, "-c", "copy", str(output_path)]
    subprocess.run(cmd, check=True)
    return output_path, "playwright-capture"


def _ixigua_mobile_url(item_id: str) -> str:
    match = re.search(r"(\d{12,})", item_id or "")
    return f"https://m.ixigua.com/video/{match.group(1)}?wid_try=1" if match else ""


def download_record(record: dict, output_dir: Path, auth_state: Path,
                    prefer_playwright: bool, timeout_ms: int) -> tuple[Path, str]:
    url = canonical_url(record.get("detail_url") or "")
    if not url:
        raise RuntimeError("record has no detail_url")
    item_id = record.get("item_id") or slugify(url)

    errors: list[str] = []
    methods = ["playwright", "ytdlp"] if prefer_playwright else ["ytdlp", "playwright"]
    for method in methods:
        try:
            if method == "ytdlp":
                return download_with_ytdlp(url, item_id, output_dir, auth_state)
            return download_with_playwright_capture(url, item_id, output_dir, auth_state, timeout_ms)
        except Exception as exc:
            errors.append(f"{method}: {exc}")

    # Toutiao original URL often triggers an app gate; retry playwright with ixigua mobile variant
    fallback_url = _ixigua_mobile_url(item_id)
    if fallback_url:
        try:
            print(f"  [fallback] trying ixigua-mobile: {fallback_url}")
            return download_with_playwright_capture(fallback_url, item_id, output_dir, auth_state, timeout_ms)
        except Exception as exc:
            errors.append(f"ixigua-mobile: {exc}")

    raise RuntimeError("download failed; " + " | ".join(errors))


def select_records(manifest: dict, new_only: bool, limit: int) -> list[dict]:
    records = list((manifest.get("items") or {}).values())
    selected = []
    for record in records:
        if new_only and existing_local_path(record):
            continue
        if new_only and record.get("download_status") == "done":
            continue
        selected.append(record)
        if limit and len(selected) >= limit:
            break
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description="Download Toutiao favorites listed in manifest")
    parser.add_argument("--manifest", type=Path, default=TOUTIAO_MANIFEST)
    parser.add_argument("--auth-state", type=Path, default=TOUTIAO_AUTH_STATE)
    parser.add_argument("--output-dir", type=Path, default=TOUTIAO_VIDEO_DIR)
    parser.add_argument("--new-only", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--prefer-playwright", action="store_true")
    parser.add_argument("--timeout-ms", type=int, default=30000)
    args = parser.parse_args()

    ensure_dirs()
    manifest = load_manifest(args.manifest)
    records = select_records(manifest, args.new_only, args.limit)
    print(f"Manifest records: {len(manifest.get('items', {}))}")
    print(f"Selected records: {len(records)}")

    if args.dry_run:
        for record in records:
            print(f"  - {record.get('item_id')} {record.get('title')} {record.get('detail_url')}")
        return 0

    for index, record in enumerate(records, 1):
        item_id = record.get("item_id") or f"item-{index}"
        print(f"[{index}/{len(records)}] download {item_id} {record.get('title', '')[:80]}")
        try:
            path, method = download_record(
                record,
                args.output_dir,
                args.auth_state,
                prefer_playwright=args.prefer_playwright,
                timeout_ms=args.timeout_ms,
            )
            record["download_status"] = "done"
            record["local_path"] = str(path)
            record["downloaded_at"] = now_iso()
            record["download_method"] = method
            record["last_error"] = ""
            print(f"  ok: {path} [{method}]")
        except Exception as exc:
            record["download_status"] = "failed"
            record["last_error"] = str(exc)
            print(f"  failed: {exc}")
        save_manifest(manifest, args.manifest)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
