from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# stream_extractors lives in the repo root, not in scripts/; ensure it's importable
# regardless of how the venv was set up.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from toutiao_common import (
    ANTI_DETECTION_ARGS,
    ANTI_DETECTION_INIT_SCRIPT,
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


MOBILE_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
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


def is_media_url(url: str) -> bool:
    lowered = url.lower()
    return any(
        token in lowered
        for token in (".mp4", ".m3u8", ".flv", "mime_type=video_mp4", "toutiaovod.com")
    )


def media_score(url: str) -> int:
    lowered = url.lower()
    if ".m3u8" in lowered:
        return 100
    if ".mp4" in lowered:
        return 90
    if "mime_type=video_mp4" in lowered or "toutiaovod.com" in lowered:
        return 90
    if ".flv" in lowered:
        return 80
    return 0


def clean_ffmpeg_headers(headers: dict[str, str]) -> dict[str, str]:
    skipped = {"accept-encoding", "connection", "content-length", "host", "range"}
    cleaned = {}
    for key, value in headers.items():
        lowered = key.lower()
        if lowered in skipped or lowered.startswith(":"):
            continue
        cleaned[key] = value
    return cleaned


def download_with_mobile_playwright_capture(
    url: str,
    item_id: str,
    output_dir: Path,
    auth_state: Path,
    timeout_ms: int,
    headed: bool,
) -> tuple[Path, str]:
    from playwright.sync_api import sync_playwright

    output_dir.mkdir(parents=True, exist_ok=True)
    candidates: list[tuple[int, str, dict[str, str]]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed, args=ANTI_DETECTION_ARGS)
        context_kwargs = {
            "viewport": {"width": 390, "height": 844},
            "locale": "zh-CN",
            "user_agent": MOBILE_USER_AGENT,
            "is_mobile": True,
            "has_touch": True,
        }
        if auth_state.exists():
            context_kwargs["storage_state"] = str(auth_state)
        context = browser.new_context(**context_kwargs)
        context.add_init_script(ANTI_DETECTION_INIT_SCRIPT)
        page = context.new_page()

        def on_request(request):
            if is_media_url(request.url):
                candidates.append((media_score(request.url), request.url, clean_ffmpeg_headers(request.headers)))

        page.on("request", on_request)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(1500)
            try:
                page.mouse.wheel(0, 480)
                page.wait_for_timeout(500)
                page.mouse.click(190, 360)
                page.wait_for_timeout(6000)
            except Exception:
                pass
        finally:
            context.close()
            browser.close()

    if not candidates:
        raise RuntimeError("mobile Playwright 未截获 .mp4/.m3u8/.flv 媒体请求")
    _, media_url, headers = sorted(candidates, key=lambda item: item[0], reverse=True)[0]
    suffix = ".mp4"
    output_path = output_dir / f"{item_id}{suffix}"
    headers.setdefault("user-agent", MOBILE_USER_AGENT)
    headers.setdefault("referer", url)
    headers_text = "".join(f"{key}: {value}\r\n" for key, value in headers.items())
    cmd = ["ffmpeg", "-y"]
    if headers_text:
        cmd += ["-headers", headers_text]
    cmd += ["-i", media_url, "-c", "copy", str(output_path)]
    subprocess.run(cmd, check=True)
    return output_path, "mobile-playwright-capture"


def download_record(record: dict, output_dir: Path, auth_state: Path,
                    prefer_playwright: bool, timeout_ms: int,
                    playwright_mobile: bool = False,
                    headed: bool = False) -> tuple[Path, str]:
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
            if playwright_mobile:
                return download_with_mobile_playwright_capture(url, item_id, output_dir, auth_state, timeout_ms, headed)
            return download_with_playwright_capture(url, item_id, output_dir, auth_state, timeout_ms)
        except Exception as exc:
            errors.append(f"{method}: {exc}")
    raise RuntimeError("download failed; " + " | ".join(errors))


def load_queue_ids(queue_json: Path | None) -> list[str]:
    if not queue_json:
        return []
    data = json.loads(queue_json.read_text(encoding="utf-8"))
    return [item.get("item_id", "") for item in data.get("items", []) if item.get("item_id")]


def select_records(manifest: dict, new_only: bool, limit: int, content_type: str,
                   queue_ids: list[str] | None = None,
                   item_ids: set[str] | None = None) -> list[dict]:
    records = list((manifest.get("items") or {}).values())
    if queue_ids:
        allowed = set(queue_ids)
        order = {item_id: index for index, item_id in enumerate(queue_ids)}
        records = [record for record in records if record.get("item_id") in allowed]
        records.sort(key=lambda record: order.get(record.get("item_id", ""), len(order)))
    if item_ids:
        records = [record for record in records if record.get("item_id") in item_ids]
    selected = []
    for record in records:
        if content_type != "all" and record.get("content_type", "video") != content_type:
            continue
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
    parser.add_argument("--queue-json", type=Path, help="Optional queue JSON from toutiao_export_missing_payload_queue.py")
    parser.add_argument("--auth-state", type=Path, default=TOUTIAO_AUTH_STATE)
    parser.add_argument("--output-dir", type=Path, default=TOUTIAO_VIDEO_DIR)
    parser.add_argument("--new-only", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--item-id", action="append", default=[], help="Restrict selection to one or more item IDs")
    parser.add_argument(
        "--content-type",
        default="video",
        choices=("video", "article", "image", "audio", "text", "mixed", "unknown", "all"),
        help="Filter manifest records by classified content_type. Defaults to video.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--prefer-playwright", action="store_true")
    parser.add_argument("--playwright-mobile", action="store_true", help="Use mobile Toutiao share page when Playwright captures media")
    parser.add_argument("--headed", action="store_true", help="Run Playwright browser headed")
    parser.add_argument("--timeout-ms", type=int, default=30000)
    args = parser.parse_args()

    ensure_dirs()
    manifest = load_manifest(args.manifest)
    queue_ids = load_queue_ids(args.queue_json)
    records = select_records(
        manifest,
        args.new_only,
        args.limit,
        args.content_type,
        queue_ids=queue_ids,
        item_ids=set(args.item_id),
    )
    print(f"Manifest records: {len(manifest.get('items', {}))}")
    if args.queue_json:
        print(f"Queue records   : {len(queue_ids)}")
    print(f"Selected records: {len(records)}")
    print(f"Content type    : {args.content_type}")

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
                playwright_mobile=args.playwright_mobile,
                headed=args.headed,
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
