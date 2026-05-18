"""
zhihuTTS_stream.py - validate processing a remote MP4 URL by time slice.

This is an experimental entrypoint for near-real-time/stream-style processing.
It does not change the main batch runner. By default it avoids Gemini calls and
only verifies that a remote URL can be sliced, preprocessed, transcribed, and
converted into the same payload shape used by the existing pipeline.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shlex
import subprocess
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from stream_extractors import ExtractedStream, PlaywrightKeepaliveStream, extract_stream, infer_media_type
from zhihuTTS_video import (
    build_gemini_payload,
    extract_keyframes,
    transcribe_audio,
    transcript_to_text,
)


ROOT_DIR = Path(__file__).parent
RUNS_DIR = ROOT_DIR / "runs"
STREAM_TMP_DIR = ROOT_DIR / "Videos" / ".stream"
FFMPEG_TIMEOUT = 7200
SLICE_RETRIES = 3
MIN_SLICE_BYTES = 1024


class StreamSliceError(RuntimeError):
    """Raised when ffmpeg cannot produce a valid media slice."""


def parse_time(value: str | float | int) -> float:
    """Parse seconds or HH:MM:SS into seconds."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return 0.0
    if ":" not in text:
        return float(text)
    parts = [float(p) for p in text.split(":")]
    if len(parts) == 2:
        minutes, seconds = parts
        return minutes * 60 + seconds
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return hours * 3600 + minutes * 60 + seconds
    raise ValueError(f"Unsupported time format: {value}")


def fmt_time(seconds: float) -> str:
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def safe_name(value: str, max_len: int = 80) -> str:
    name = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", value, flags=re.UNICODE).strip("._")
    return (name or "stream")[:max_len]


def parse_headers_text(text: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"Invalid header line: {raw_line}")
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            headers[key] = value
    return headers


def parse_headers_file(path: str) -> dict[str, str]:
    return parse_headers_text(Path(path).read_text(encoding="utf-8"))


def overlay_headers(args: argparse.Namespace) -> dict[str, str]:
    headers: dict[str, str] = {}
    if args.headers_file:
        headers.update(parse_headers_file(args.headers_file))
    return headers


def parse_curl_file(path: str) -> tuple[str, dict[str, str]]:
    text = Path(path).read_text(encoding="utf-8")
    tokens = shlex.split(text.replace("\\\n", " "))
    if not tokens or tokens[0] != "curl":
        raise ValueError("--curl-file must contain a command copied as cURL")

    url = ""
    headers: dict[str, str] = {}
    index = 1
    while index < len(tokens):
        token = tokens[index]
        next_value = tokens[index + 1] if index + 1 < len(tokens) else ""

        if token in ("-H", "--header"):
            headers.update(parse_headers_text(next_value))
            index += 2
            continue
        if token.startswith("-H") and len(token) > 2:
            headers.update(parse_headers_text(token[2:].strip()))
            index += 1
            continue
        if token.startswith("--header="):
            headers.update(parse_headers_text(token.split("=", 1)[1]))
            index += 1
            continue
        if token in ("-A", "--user-agent"):
            headers["User-Agent"] = next_value
            index += 2
            continue
        if token.startswith("--user-agent="):
            headers["User-Agent"] = token.split("=", 1)[1]
            index += 1
            continue
        if token in ("-e", "--referer"):
            headers["Referer"] = next_value
            index += 2
            continue
        if token.startswith("--referer="):
            headers["Referer"] = token.split("=", 1)[1]
            index += 1
            continue
        if token in ("-b", "--cookie", "--cookie-jar"):
            if token != "--cookie-jar":
                headers["Cookie"] = next_value
            index += 2
            continue
        if token.startswith("--cookie="):
            headers["Cookie"] = token.split("=", 1)[1]
            index += 1
            continue
        if token.startswith("http://") or token.startswith("https://") or token.startswith("rtmp://") or token.startswith("rtsp://"):
            url = token
        index += 1

    if not url:
        raise ValueError("No media URL found in --curl-file")
    return url, headers


def build_ffmpeg_headers(headers: dict[str, str]) -> str:
    return "".join(f"{key}: {value}\r\n" for key, value in headers.items())


def with_headers(cmd: list[str], headers: dict[str, str]) -> list[str]:
    if not headers:
        return cmd
    return cmd[:1] + ["-headers", build_ffmpeg_headers(headers)] + cmd[1:]


def resolve_input(args: argparse.Namespace) -> ExtractedStream:
    if args.playwright_keepalive:
        raise ValueError("--playwright-keepalive is handled by the validation runner")
    url = args.url
    headers: dict[str, str] = {}
    if args.curl_file:
        url, headers = parse_curl_file(args.curl_file)
    headers.update(overlay_headers(args))
    if url:
        return ExtractedStream(
            url=url,
            headers=headers,
            extractor="curl-file" if args.curl_file else "direct",
            media_type=infer_media_type(url),
            page_url=args.page_url or "",
        )
    if args.page_url:
        stream = extract_stream(
            args.page_url,
            extractor=args.extractor,
            storage_state=args.playwright_storage_state,
            save_storage_state=args.playwright_save_storage_state,
            user_data_dir=args.playwright_user_data_dir,
            headed=args.playwright_headed,
            timeout_ms=args.extractor_timeout_ms,
            wait_seconds=args.extractor_wait_s,
            ytdlp_cookies_browser=args.ytdlp_cookies_browser,
        )
        if headers:
            stream.headers.update(headers)
        return stream
    raise ValueError("Provide --url, --curl-file, or --page-url")


def refresh_page_stream(args: argparse.Namespace) -> ExtractedStream:
    if not args.page_url:
        raise RuntimeError("Cannot refresh stream without --page-url")
    stream = extract_stream(
        args.page_url,
        extractor=args.extractor,
        storage_state=args.playwright_storage_state,
        save_storage_state=args.playwright_save_storage_state,
        user_data_dir=args.playwright_user_data_dir,
        headed=args.playwright_headed,
        timeout_ms=args.extractor_timeout_ms,
        wait_seconds=args.extractor_wait_s,
        ytdlp_cookies_browser=args.ytdlp_cookies_browser,
    )
    stream.headers.update(overlay_headers(args))
    return stream


def start_keepalive_stream(args: argparse.Namespace) -> tuple[PlaywrightKeepaliveStream, ExtractedStream]:
    if not args.page_url:
        raise ValueError("--playwright-keepalive requires --page-url")
    if args.url or args.curl_file:
        raise ValueError("--playwright-keepalive cannot be combined with --url or --curl-file")
    if args.extractor not in ("auto", "playwright"):
        raise ValueError("--playwright-keepalive requires --extractor playwright or auto")
    keepalive = PlaywrightKeepaliveStream(
        args.page_url,
        storage_state=args.playwright_storage_state,
        save_storage_state=args.playwright_save_storage_state,
        user_data_dir=args.playwright_user_data_dir,
        headed=args.playwright_headed,
        timeout_ms=args.extractor_timeout_ms,
        wait_seconds=args.extractor_wait_s,
    )
    try:
        stream = keepalive.start()
    except Exception:
        keepalive.close()
        raise
    stream.headers.update(overlay_headers(args))
    return keepalive, stream


def redacted_error(error: Exception, stream: ExtractedStream) -> str:
    text = str(error)
    if stream.url:
        text = text.replace(stream.url, "<redacted-url>")
    return text


def probe_url(url: str, headers: dict[str, str] | None = None) -> dict:
    cmd = [
        "ffprobe",
        "-hide_banner",
        "-v",
        "warning",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        url,
    ]
    cmd = with_headers(cmd, headers or {})
    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        timeout=FFMPEG_TIMEOUT,
    )
    return json.loads(completed.stdout)


def slice_url(
    url: str,
    start_s: float,
    duration_s: float,
    out_path: Path,
    headers: dict[str, str] | None = None,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-v",
        "warning",
        "-y",
        "-ss",
        fmt_time(start_s),
        "-reconnect",
        "1",
        "-reconnect_streamed",
        "1",
        "-reconnect_on_network_error",
        "1",
        "-reconnect_delay_max",
        "10",
        "-i",
        url,
        "-t",
        str(duration_s),
        "-c",
        "copy",
        str(out_path),
    ]
    cmd = with_headers(cmd, headers or {})
    last_error = ""
    for attempt in range(1, SLICE_RETRIES + 1):
        if out_path.exists():
            out_path.unlink()
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=FFMPEG_TIMEOUT,
        )
        size = out_path.stat().st_size if out_path.exists() else 0
        if completed.returncode == 0 and size >= MIN_SLICE_BYTES:
            return
        last_error = (completed.stderr or completed.stdout or "").replace(url, "<redacted-url>")
        print(
            f"  Slice attempt {attempt}/{SLICE_RETRIES} failed "
            f"(exit={completed.returncode}, bytes={size}); retrying..."
        )
        if out_path.exists():
            out_path.unlink()
        if attempt < SLICE_RETRIES:
            time.sleep(min(30, attempt * 5))
    tail = "\n".join(last_error.splitlines()[-12:])
    raise StreamSliceError(
        f"Failed to slice {fmt_time(start_s)} + {fmt_time(duration_s)} "
        f"after {SLICE_RETRIES} attempts.\n{tail}"
    )


def summarize_probe(probe: dict) -> dict:
    fmt = probe.get("format", {})
    streams = probe.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    return {
        "duration_s": float(fmt.get("duration") or 0),
        "size_bytes": int(fmt.get("size") or 0),
        "bit_rate": int(fmt.get("bit_rate") or 0),
        "video": {
            "codec": video.get("codec_name"),
            "width": video.get("width"),
            "height": video.get("height"),
            "fps": video.get("avg_frame_rate") or video.get("r_frame_rate"),
        },
        "audio": {
            "codec": audio.get("codec_name"),
            "sample_rate": audio.get("sample_rate"),
            "channels": audio.get("channels"),
        },
    }


def write_report(report_path: Path, data: dict) -> None:
    lines = [
        "# Stream URL Validation",
        "",
        f"- Created: `{data['created_at']}`",
        f"- URL host: `{data['url_host']}`",
        f"- Extractor: `{data['extractor']}`",
        f"- Media type: `{data['media_type']}`",
        f"- Source duration: `{fmt_time(data['source']['duration_s'])}`",
        f"- Source size: `{data['source']['size_bytes']}` bytes",
        f"- Auth headers: `{', '.join(data['auth_header_names']) or 'none'}`",
        f"- Slice start: `{fmt_time(data['slice']['start_s'])}`",
        f"- Slice duration: `{fmt_time(data['slice']['duration_s'])}`",
        f"- Slice file: `{data['slice']['path']}`",
        f"- Slice size: `{data['slice']['size_bytes']}` bytes",
        f"- Slice kept: `{data['slice']['kept']}`",
        f"- Stream re-extractions: `{data['processing']['stream_reextracts']}`",
        "",
        "## Processing",
        "",
        f"- Keyframe events: `{data['processing']['events']}`",
        f"- Kept frames: `{data['processing']['frames']}`",
        f"- Backend: `{data['processing']['backend']}`",
        f"- Transcribe duration: `{data['processing']['transcribe_duration_s']}` seconds",
        f"- Transcript segments: `{data['processing']['segments']}`",
        f"- Transcript chars: `{data['processing']['transcript_chars']}`",
        "",
        "## Output Files",
        "",
        f"- Transcript text: `{data['outputs']['transcript_txt']}`",
        f"- Payload JSON: `{data['outputs']['payload_json']}`",
        "",
        "## Transcript Preview",
        "",
        "```text",
        data["transcript_preview"],
        "```",
        "",
        "## Full Global Transcript",
        "",
        "```text",
        data["global_transcript_text"],
        "```",
        "",
    ]
    if data["recovery_errors"]:
        lines.extend(["## Recovery Errors", ""])
        for index, error in enumerate(data["recovery_errors"], 1):
            lines.append(f"{index}. `{error.splitlines()[-1][:300]}`")
        lines.append("")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


def offset_transcript_text(transcript: dict, offset_s: float) -> str:
    """Render transcript with timestamps offset to the source-video timeline."""
    lines = []
    for seg in transcript["segments"]:
        start = float(seg["start"]) + offset_s
        end = float(seg["end"]) + offset_s
        lines.append(f"[{fmt_time(start)} - {fmt_time(end)}] {seg['text']}")
    return "\n".join(lines)


def process_slice(
    args: argparse.Namespace,
    url: str,
    headers: dict[str, str],
    host: str,
    source_summary: dict,
    base_stem: str,
    start_s: float,
    duration_s: float,
    chunk_index: int,
    chunk_total: int,
    reextracts: int = 0,
    recovery_errors: list[str] | None = None,
) -> dict:
    started = time.monotonic()
    created_at = datetime.now().isoformat(timespec="seconds")
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slice_stem = safe_name(f"{base_stem}_chunk{chunk_index:03d}_{int(start_s)}s")
    stream_work_dir = Path(args.stream_work_dir or STREAM_TMP_DIR)
    slice_path = stream_work_dir / f"{slice_stem}.mp4"
    print(f"Slicing {fmt_time(start_s)} + {fmt_time(duration_s)} -> {slice_path}")
    slice_url(url, start_s, duration_s, slice_path, headers)

    events, frames = extract_keyframes(slice_path)
    transcript = transcribe_audio(slice_path)
    transcript_text = transcript_to_text(transcript)
    global_transcript_text = offset_transcript_text(transcript, start_s)
    payload = build_gemini_payload(slice_path.stem, transcript, events, frames)

    transcript_path = RUNS_DIR / f"stream-{slice_stem}-{timestamp}.transcript.txt"
    global_transcript_path = RUNS_DIR / f"stream-{slice_stem}-{timestamp}.global-transcript.txt"
    payload_path = RUNS_DIR / f"stream-{slice_stem}-{timestamp}.payload.json"
    report_path = RUNS_DIR / f"stream-{slice_stem}-{timestamp}.md"

    RUNS_DIR.mkdir(exist_ok=True)
    transcript_path.write_text(transcript_text, encoding="utf-8")
    global_transcript_path.write_text(global_transcript_text, encoding="utf-8")
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    slice_size = slice_path.stat().st_size
    slice_kept = not args.cleanup_slices
    if args.cleanup_slices:
        slice_path.unlink(missing_ok=True)

    data = {
        "created_at": created_at,
        "url_host": host,
        "extractor": source_summary.get("extractor", "unknown"),
        "media_type": source_summary.get("media_type", "unknown"),
        "source": source_summary,
        "auth_header_names": sorted(headers.keys()),
        "slice": {
            "start_s": start_s,
            "duration_s": duration_s,
            "path": str(slice_path),
            "size_bytes": slice_size,
            "kept": slice_kept,
        },
        "processing": {
            "events": len(events),
            "frames": len(frames),
            "backend": transcript.get("backend_used"),
            "transcribe_duration_s": transcript.get("duration_s"),
            "segments": len(transcript.get("segments", [])),
            "transcript_chars": len(transcript_text),
            "elapsed_s": round(time.monotonic() - started, 2),
            "stream_reextracts": reextracts,
        },
        "recovery_errors": recovery_errors or [],
        "outputs": {
            "transcript_txt": str(transcript_path),
            "payload_json": str(payload_path),
            "report_md": str(report_path),
            "global_transcript_txt": str(global_transcript_path),
        },
        "chunk": {
            "index": chunk_index,
            "total": chunk_total,
        },
        "transcript_preview": transcript_text[:1000],
        "global_transcript_preview": global_transcript_text[:1000],
        "global_transcript_text": global_transcript_text,
    }
    write_report(report_path, data)
    print(f"Report: {report_path}")
    print(f"Elapsed: {data['processing']['elapsed_s']}s")
    return data


def process_slice_with_recovery(
    args: argparse.Namespace,
    stream: ExtractedStream,
    source_summary: dict,
    base_stem: str,
    start_s: float,
    duration_s: float,
    chunk_index: int,
    chunk_total: int,
    keepalive: PlaywrightKeepaliveStream | None = None,
) -> tuple[dict, ExtractedStream, dict]:
    current_stream = stream
    current_summary = source_summary
    recovery_errors: list[str] = []
    max_reextracts = max(0, args.reextract_retries) if args.page_url else 0
    reextract_count = 0

    while True:
        if keepalive:
            current_stream = keepalive.latest_stream()
            current_stream.headers.update(overlay_headers(args))
        host = urlparse(current_stream.url).hostname or "unknown-host"
        try:
            chunk = process_slice(
                args,
                current_stream.url,
                current_stream.headers,
                host,
                current_summary,
                base_stem,
                start_s,
                duration_s,
                chunk_index,
                chunk_total,
                reextracts=reextract_count,
                recovery_errors=recovery_errors,
            )
            return chunk, current_stream, current_summary
        except StreamSliceError as e:
            if reextract_count >= max_reextracts:
                raise
            message = redacted_error(e, current_stream)
            recovery_errors.append(message)

            while reextract_count < max_reextracts:
                reextract_count += 1
                print(
                    f"  Chunk {chunk_index} failed after ffmpeg slicing; "
                    f"refreshing stream URL ({reextract_count}/{max_reextracts})..."
                )
                if args.reextract_delay_s > 0:
                    time.sleep(args.reextract_delay_s)

                refreshed_stream: ExtractedStream | None = None
                try:
                    if keepalive:
                        refreshed_stream = keepalive.refresh_and_get(args.keepalive_refresh_wait_s)
                        refreshed_stream.headers.update(overlay_headers(args))
                    else:
                        refreshed_stream = refresh_page_stream(args)
                    print(
                        "  Refreshed stream:",
                        refreshed_stream.extractor,
                        refreshed_stream.media_type,
                        urlparse(refreshed_stream.url).hostname or "unknown-host",
                    )
                    refreshed_probe = probe_url(refreshed_stream.url, refreshed_stream.headers)
                    refreshed_summary = summarize_probe(refreshed_probe)
                    refreshed_summary["extractor"] = refreshed_stream.extractor
                    refreshed_summary["media_type"] = refreshed_stream.media_type
                    current_stream = refreshed_stream
                    current_summary = refreshed_summary
                    break
                except Exception as refresh_error:
                    redaction_stream = refreshed_stream or current_stream
                    recovery_errors.append(redacted_error(refresh_error, redaction_stream))
                    if reextract_count >= max_reextracts:
                        raise StreamSliceError(
                            f"Failed to refresh stream URL after {max_reextracts} re-extract attempts"
                        ) from refresh_error
                    print(
                        f"  Stream URL refresh failed; retrying extractor "
                        f"({reextract_count + 1}/{max_reextracts})..."
                    )


def write_manifest(manifest_path: Path, data: dict) -> None:
    chunks = data["chunks"]
    total_elapsed = sum(c["processing"]["elapsed_s"] for c in chunks)
    total_segments = sum(c["processing"]["segments"] for c in chunks)
    total_chars = sum(c["processing"]["transcript_chars"] for c in chunks)
    total_frames = sum(c["processing"]["frames"] for c in chunks)
    total_reextracts = sum(c["processing"].get("stream_reextracts", 0) for c in chunks)
    kept_slices = sum(1 for c in chunks if c["slice"].get("kept", True))
    lines = [
        "# Stream Multi-Slice Validation",
        "",
        f"- Created: `{data['created_at']}`",
        f"- URL host: `{data['url_host']}`",
        f"- Extractor: `{data['extractor']}`",
        f"- Media type: `{data['media_type']}`",
        f"- Source duration: `{fmt_time(data['source']['duration_s'])}`",
        f"- Source size: `{data['source']['size_bytes']}` bytes",
        f"- Auth headers: `{', '.join(data['auth_header_names']) or 'none'}`",
        f"- Covered start: `{fmt_time(data['start_s'])}`",
        f"- Covered duration: `{fmt_time(data['duration_s'])}`",
        f"- Chunk duration: `{fmt_time(data['chunk_duration_s'])}`",
        f"- Chunks: `{len(chunks)}`",
        f"- Processing elapsed sum: `{round(total_elapsed, 2)}` seconds",
        f"- Transcript segments: `{total_segments}`",
        f"- Transcript chars: `{total_chars}`",
        f"- Kept frames: `{total_frames}`",
        f"- Stream re-extractions: `{total_reextracts}`",
        f"- Slice files kept: `{kept_slices}/{len(chunks)}`",
        "",
        "## Outputs",
        "",
        f"- Combined transcript: `{data['combined_transcript_path']}`",
        f"- Manifest JSON: `{data['manifest_json_path']}`",
        "",
        "## Chunks",
        "",
        "| # | Start | Duration | Backend | Transcribe s | Segments | Chars | Frames | Re-extracts | Slice kept | Report |",
        "|---:|---|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for chunk in chunks:
        proc = chunk["processing"]
        outs = chunk["outputs"]
        lines.append(
            "| {idx} | {start} | {duration} | `{backend}` | {transcribe} | {segments} | {chars} | {frames} | {reextracts} | {slice_kept} | `{report}` |".format(
                idx=chunk["chunk"]["index"],
                start=fmt_time(chunk["slice"]["start_s"]),
                duration=fmt_time(chunk["slice"]["duration_s"]),
                backend=proc["backend"],
                transcribe=proc["transcribe_duration_s"],
                segments=proc["segments"],
                chars=proc["transcript_chars"],
                frames=proc["frames"],
                reextracts=proc.get("stream_reextracts", 0),
                slice_kept=chunk["slice"].get("kept", True),
                report=outs["report_md"],
            )
        )
    lines.extend(
        [
            "",
            "## Combined Transcript Preview",
            "",
            "```text",
            data["preview"],
            "```",
            "",
            "## Full Combined Transcript",
            "",
            "```text",
            data["combined_transcript_text"],
            "```",
            "",
        ]
    )
    manifest_path.write_text("\n".join(lines), encoding="utf-8")


def run_validation(args: argparse.Namespace) -> dict:
    keepalive: PlaywrightKeepaliveStream | None = None
    try:
        if args.playwright_keepalive:
            keepalive, stream = start_keepalive_stream(args)
        else:
            stream = resolve_input(args)
        url = stream.url
        headers = stream.headers
        start_s = parse_time(args.start)
        requested_duration_s = parse_time(args.duration)
        chunk_duration_s = parse_time(args.chunk_duration or args.duration)
        created_at = datetime.now().isoformat(timespec="seconds")
        host = urlparse(url).hostname or "unknown-host"

        print(f"Input extractor: {stream.extractor} ({stream.media_type})")
        if stream.page_url:
            print(f"Page URL host: {urlparse(stream.page_url).hostname or 'unknown-host'}")
        print("Probing remote media...")
        probe = probe_url(url, headers)
        source_summary = summarize_probe(probe)
        source_summary["extractor"] = stream.extractor
        source_summary["media_type"] = stream.media_type
        if requested_duration_s <= 0:
            requested_duration_s = max(0, source_summary["duration_s"] - start_s)
        if chunk_duration_s <= 0:
            raise ValueError("--chunk-duration must be greater than zero")

        print(
            "Source:",
            fmt_time(source_summary["duration_s"]),
            f"{source_summary['size_bytes']} bytes",
            source_summary["video"],
            source_summary["audio"],
        )
        if headers:
            print("Auth headers:", ", ".join(sorted(headers.keys())))

        base_stem = safe_name(args.name or f"{host}_{int(start_s)}_{int(requested_duration_s)}")
        chunk_count = math.ceil(requested_duration_s / chunk_duration_s)
        if args.max_chunks:
            chunk_count = min(chunk_count, args.max_chunks)

        chunks = []
        for index in range(1, chunk_count + 1):
            chunk_start = start_s + (index - 1) * chunk_duration_s
            remaining = start_s + requested_duration_s - chunk_start
            if remaining <= 0:
                break
            chunk_duration = min(chunk_duration_s, remaining)
            print(f"\n=== Chunk {index}/{chunk_count}: {fmt_time(chunk_start)} + {fmt_time(chunk_duration)} ===")
            chunk, stream, source_summary = process_slice_with_recovery(
                args,
                stream,
                source_summary,
                base_stem,
                chunk_start,
                chunk_duration,
                index,
                chunk_count,
                keepalive=keepalive,
            )
            url = stream.url
            headers = stream.headers
            host = urlparse(url).hostname or "unknown-host"
            chunks.append(chunk)

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        combined_text = "\n\n".join(
            Path(c["outputs"]["global_transcript_txt"]).read_text(encoding="utf-8")
            for c in chunks
        )
        combined_transcript_path = RUNS_DIR / f"stream-{base_stem}-{timestamp}.combined-transcript.txt"
        manifest_json_path = RUNS_DIR / f"stream-{base_stem}-{timestamp}.manifest.json"
        manifest_md_path = RUNS_DIR / f"stream-{base_stem}-{timestamp}.manifest.md"
        combined_transcript_path.write_text(combined_text, encoding="utf-8")

        manifest = {
            "created_at": created_at,
            "url_host": host,
            "extractor": stream.extractor,
            "media_type": stream.media_type,
            "source": source_summary,
            "auth_header_names": sorted(headers.keys()),
            "start_s": start_s,
            "duration_s": requested_duration_s,
            "chunk_duration_s": chunk_duration_s,
            "chunks": chunks,
            "combined_transcript_path": str(combined_transcript_path),
            "manifest_json_path": str(manifest_json_path),
            "manifest_md_path": str(manifest_md_path),
            "combined_transcript_text": combined_text,
            "preview": combined_text[:1200],
        }
        manifest_json_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        write_manifest(manifest_md_path, manifest)
        print(f"\nManifest: {manifest_md_path}")
        print(f"Combined transcript: {combined_transcript_path}")
        return manifest
    finally:
        if keepalive:
            keepalive.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate processing a remote MP4 URL slice.")
    parser.add_argument("--url", default="", help="Remote MP4/HLS URL readable by ffmpeg.")
    parser.add_argument("--page-url", default="", help="Live room or replay page URL to auto-extract media from.")
    parser.add_argument(
        "--extractor",
        choices=("auto", "ytdlp", "playwright"),
        default="auto",
        help="Extractor for --page-url. auto routes known sites to yt-dlp or Playwright.",
    )
    parser.add_argument(
        "--ytdlp-cookies-browser",
        default="",
        help="Optional browser name for yt-dlp cookies, for example chrome.",
    )
    parser.add_argument(
        "--playwright-storage-state",
        default="",
        help="Optional Playwright storage_state JSON for logged-in pages.",
    )
    parser.add_argument(
        "--playwright-save-storage-state",
        default="",
        help="Optional path to write refreshed Playwright storage_state after extraction.",
    )
    parser.add_argument(
        "--playwright-user-data-dir",
        default="",
        help="Optional persistent Playwright browser profile directory for cookie/session reuse.",
    )
    parser.add_argument(
        "--playwright-headed",
        action="store_true",
        help="Run Playwright with a visible browser for debugging.",
    )
    parser.add_argument(
        "--playwright-keepalive",
        action="store_true",
        help="Keep the Playwright page open during the whole run and reuse latest media requests.",
    )
    parser.add_argument(
        "--keepalive-refresh-wait-s",
        type=float,
        default=8.0,
        help="Seconds to wait for a new media request after refreshing a keepalive page.",
    )
    parser.add_argument(
        "--extractor-timeout-ms",
        type=int,
        default=20000,
        help="Page navigation timeout for Playwright extraction.",
    )
    parser.add_argument(
        "--extractor-wait-s",
        type=float,
        default=8.0,
        help="Seconds to keep listening for media requests after page load.",
    )
    parser.add_argument(
        "--reextract-retries",
        type=int,
        default=2,
        help="When --page-url is used, re-extract media URL this many times after slice failure.",
    )
    parser.add_argument(
        "--reextract-delay-s",
        type=float,
        default=10.0,
        help="Seconds to wait before re-extracting after slice failure.",
    )
    parser.add_argument(
        "--headers-file",
        default="",
        help="Optional auth headers file with one 'Header: value' line per header.",
    )
    parser.add_argument(
        "--curl-file",
        default="",
        help="Optional DevTools 'Copy as cURL' command file. URL and headers are parsed from it.",
    )
    parser.add_argument("--start", default="0", help="Slice start, seconds or HH:MM:SS.")
    parser.add_argument(
        "--duration",
        default="180",
        help="Total validation window duration. Use 0 to process from start to source end.",
    )
    parser.add_argument(
        "--chunk-duration",
        default="",
        help="Per-slice duration. Defaults to --duration, so one chunk is processed.",
    )
    parser.add_argument(
        "--stream-work-dir",
        default=str(STREAM_TMP_DIR),
        help="Directory for temporary stream slice MP4 files.",
    )
    parser.add_argument(
        "--cleanup-slices",
        action="store_true",
        help="Delete each slice MP4 after keyframes, transcript, payload, and report are written.",
    )
    parser.add_argument("--max-chunks", type=int, default=0, help="Optional cap for smoke tests.")
    parser.add_argument("--name", default="", help="Optional output stem.")
    parser.add_argument(
        "--no-gemini",
        action="store_true",
        help="Accepted for compatibility; this validation script never calls Gemini.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    run_validation(args)


if __name__ == "__main__":
    main()
