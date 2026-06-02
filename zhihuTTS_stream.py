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
import os
import re
import shlex
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from stream_extractors import (
    ExtractedStream,
    PlaywrightKeepaliveStream,
    extract_stream,
    infer_media_type,
    is_ytdlp_stream_ended_error,
)
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
MAX_BROWSER_RESTARTS = 3

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_MAX_RETRIES = 6
GEMINI_RETRY_DELAY = 65
GEMINI_MAX_CONTINUATIONS = 20
GEMINI_CONTINUATION_COOLDOWN = 6   # free tier: 10 RPM → 1 req / 6 s

GEMINI_PROMPT_TEXT = """
# 角色与目标
你是一个顶级的知识库数据提取专家。我将提供一段视频的**完整逐字稿（带时间戳）**和**关键帧截图（包含幻灯片切换和画笔标注）**，请将它们视为完整的视频内容，提取转化为一份**高度详尽、结构化、完全适合导入 NotebookLM 作为底层语料的 Markdown 文档**。

# 输入说明
- **逐字稿**: 包含每个段落的开始和结束时间戳 [HH:MM:SS]
- **关键帧**: 按时间顺序排列的视频截图，包括：
  - 幻灯片切换时的完整画面
  - 讲师使用画笔标注时的画面（包含标注前和标注后的帧）
- 请结合文字和截图共同理解视频内容，当截图中的画面与逐字稿不对应时，以截图中的视觉信息为准。

# 提取原则（至关重要）
1. **拒绝极简摘要：** 我需要的是"重型知识沉淀"，请尽可能详尽地提取视频中的具体细节、核心论点、数据支撑和案例，而不是只给我大纲。
2. **提取视觉信息：** 关键帧包含了幻灯片内容、代码截图、架构图和画笔标注。请务必用文字把屏幕上看到的核心内容"转录"下来，并附上描述。
3. **保留专业术语：** 精准提取视频中的专有名词、工具名称、人名和核心概念，不要做通俗化处理，确保后续检索的准确性。
4. **时间线锚点：** 请按照视频的逻辑章节或时间块进行切分，并在每个段落前标注大致的时间戳（如 [00:15:20]）。

# 必须输出的 Markdown 结构

请严格按照以下模板输出内容：

## 1. 视频元数据
- **推测主题：** （用一句话概括视频核心内容）
- **核心关键词：** （提供 5-10 个便于检索的关键词/标签）
- **适用受众/场景：** （这段视频主要解决什么问题）

## 2. 核心知识字典（Glossary）
（提取视频中反复出现的 3-5 个核心概念或专业术语，并给出视频中的定义，帮助 LLM 统一概念）

## 3. 详尽内容解析（按时间线或章节）
（请根据视频长度，拆分为多个逻辑章节。针对每个章节，请提供：）
### [开始时间 - 结束时间] 章节标题
- **核心论点：** （本段的重点结论）
- **详细展开：** （详尽记录演讲者的具体解释、举例和论证过程）
- **视觉/屏幕内容：** （如果屏幕上有图表、文字、代码或演示操作，请详细描述。如果是代码或配置，请使用代码块 ``` 包裹）
- **重要金句/原话：** （提取 1-2 句演讲者的关键原话，加上引号）

## 4. 遗留问题与下一步行动（如有）
（视频结尾提到的待办事项、推荐的拓展资源，或未解决的问题）

# 执行要求
由于视频长达 2-3 小时，信息量极大。请保持极高的专注度，不要省略中间章节。如果你的输出达到了字数上限，请停在当前完整的段落，我会回复"继续"，你再接着上文输出。
"""


class StreamSliceError(RuntimeError):
    """Raised when ffmpeg cannot produce a valid media slice."""


class StreamEndedError(Exception):
    """Live stream confirmed ended — breaks the run loop cleanly."""


class BrowserDeadError(Exception):
    """Playwright browser process is gone — caller should attempt restart."""


def _parse_gemini_retry_delay(error: Exception) -> int:
    match = re.search(r"retry in (\d+(?:\.\d+)?)s", str(error), re.IGNORECASE)
    return int(float(match.group(1))) + 10 if match else GEMINI_RETRY_DELAY


def _call_gemini_stream(client, parts: list, label: str) -> dict:
    """Call Gemini with rate-limit retry and MAX_TOKENS auto-continuation."""
    try:
        from google.genai import types as _gtypes
    except ImportError:
        raise ImportError("google-genai not installed — run: pip install google-genai")

    gemini_config = _gtypes.GenerateContentConfig(
        temperature=0.1,
        max_output_tokens=65536,
        thinking_config=_gtypes.ThinkingConfig(thinking_budget=0),
    )
    gemini_calls = 0
    for attempt in range(1, GEMINI_MAX_RETRIES + 1):
        try:
            print(f"[{label}] Sending to Gemini ({len(parts)} parts)...", flush=True)
            chat = client.chats.create(model=GEMINI_MODEL, config=gemini_config)
            gemini_calls += 1
            response = chat.send_message(parts)
            text = response.text
            if not text:
                raise RuntimeError("Gemini returned empty response")
            full_text = text
            candidate = response.candidates[0] if response.candidates else None
            for cont in range(GEMINI_MAX_CONTINUATIONS):
                if not candidate or candidate.finish_reason != _gtypes.FinishReason.MAX_TOKENS:
                    break
                print(f"[{label}] Output truncated, continuing ({cont + 1}/{GEMINI_MAX_CONTINUATIONS})...", flush=True)
                gemini_calls += 1
                time.sleep(GEMINI_CONTINUATION_COOLDOWN)
                response = chat.send_message("继续")
                text = response.text
                if not text:
                    break
                full_text += "\n" + text
                candidate = response.candidates[0] if response.candidates else None
            return {"text": full_text, "gemini_calls": gemini_calls}
        except Exception as e:
            is_rate_limited = "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)
            if is_rate_limited:
                delay = _parse_gemini_retry_delay(e)
                print(f"[{label}] Rate limited (429), retrying in {delay}s...", flush=True)
            else:
                delay = GEMINI_RETRY_DELAY
                print(f"[{label}] Gemini error: {e}", flush=True)
            if attempt < GEMINI_MAX_RETRIES:
                time.sleep(delay)
    return {"text": None, "gemini_calls": gemini_calls}


_GEMINI_IMAGE_HARD_LIMIT = 3000   # Gemini 2.5 Flash API ceiling


def build_stream_gemini_parts(manifest: dict) -> list:
    """Build Gemini input parts: transcript + all keyframes from all chunks.

    All kept frames are sent to maximise Gemini's multimodal understanding.
    Priority sampling (slide > annotation > context) only kicks in when the
    total exceeds _GEMINI_IMAGE_HARD_LIMIT (3000).
    """
    try:
        from google.genai import types as _gtypes
    except ImportError:
        raise ImportError("google-genai not installed — run: pip install google-genai")

    transcript_text = manifest.get("combined_transcript_text", "")

    all_frames: list[dict] = []

    def _gfmt(secs: float) -> str:
        h, r = divmod(int(secs), 3600); m, s = divmod(r, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    for chunk in manifest.get("chunks", []):
        chunk_start_s = chunk.get("slice", {}).get("start_s", 0)
        payload_path_str = chunk.get("outputs", {}).get("payload_json", "")
        if payload_path_str and Path(payload_path_str).exists():
            try:
                payload = json.loads(Path(payload_path_str).read_text(encoding="utf-8"))
                for f in payload.get("frames", []):
                    f = dict(f)
                    global_ts = chunk_start_s + f.get("timestamp_s", 0)
                    f["timestamp_s"] = global_ts
                    if f.get("marker"):
                        f["marker"] = re.sub(
                            r'Frame \[\d+:\d+:\d+\]',
                            f'Frame [{_gfmt(global_ts)}]',
                            f["marker"],
                        )
                    all_frames.append(f)
            except Exception:
                pass

    all_frames.sort(key=lambda f: f.get("timestamp_s", 0))

    if len(all_frames) > _GEMINI_IMAGE_HARD_LIMIT:
        slide_frames = [f for f in all_frames if "type=slide"      in f.get("marker", "")]
        annot_frames = [f for f in all_frames if "type=annotation" in f.get("marker", "")]
        ctx_frames   = [f for f in all_frames
                        if "type=slide"      not in f.get("marker", "")
                        and "type=annotation" not in f.get("marker", "")]
        cap      = _GEMINI_IMAGE_HARD_LIMIT
        selected = list(slide_frames[:cap])
        remaining = cap - len(selected)
        if remaining > 0:
            step = max(1, len(annot_frames) // remaining)
            selected += annot_frames[::step][:remaining]
            remaining = cap - len(selected)
        if remaining > 0 and ctx_frames:
            step = max(1, len(ctx_frames) // remaining)
            selected += ctx_frames[::step][:remaining]
        selected.sort(key=lambda f: f.get("timestamp_s", 0))
    else:
        selected = all_frames

    parts: list = [GEMINI_PROMPT_TEXT, transcript_text]
    frame_count = 0
    for frame in selected:
        frame_path = Path(frame.get("path", ""))
        if not frame_path.exists():
            continue
        parts.append(frame.get("marker", f"[Frame @{frame.get('timestamp_s', '?')}s]"))
        parts.append(_gtypes.Part(inline_data=_gtypes.Blob(
            mime_type="image/jpeg",
            data=frame_path.read_bytes(),
        )))
        frame_count += 1

    slide_count = sum(1 for f in selected if "type=slide"      in f.get("marker", ""))
    annot_count = sum(1 for f in selected if "type=annotation" in f.get("marker", ""))
    print(f"  Gemini parts built: transcript {len(transcript_text):,} chars, "
          f"{frame_count}/{len(all_frames)} frames "
          f"(slide={slide_count}, annot={annot_count})", flush=True)
    return parts


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


_FFMPEG_SKIP_HEADERS = {
    "range",
    "host",
    "connection",
    "accept-encoding",
    "transfer-encoding",
    "content-length",
    "content-type",
}


def build_ffmpeg_headers(headers: dict[str, str]) -> str:
    return "".join(
        f"{key}: {value}\r\n"
        for key, value in headers.items()
        if key.lower() not in _FFMPEG_SKIP_HEADERS
    )


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
    is_live = infer_media_type(url) in ("flv",)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-v",
        "warning",
        "-y",
    ]
    if not is_live:
        cmd += ["-ss", fmt_time(start_s)]
    cmd += [
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
    # Live FLV slices finish in roughly chunk_duration seconds of real time.
    # Tight timeout: 1× duration + 45s connection/startup buffer.
    # TimeoutExpired → StreamSliceError so the caller's is_stream_ended() check fires.
    effective_timeout = int(duration_s + 45) if is_live else FFMPEG_TIMEOUT
    last_error = ""
    for attempt in range(1, SLICE_RETRIES + 1):
        if out_path.exists():
            out_path.unlink()
        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=effective_timeout,
            )
        except subprocess.TimeoutExpired:
            if out_path.exists():
                out_path.unlink()
            raise StreamSliceError(
                f"ffmpeg timed out after {effective_timeout}s at {fmt_time(start_s)} "
                f"(live={is_live}) — stream may have ended"
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
) -> dict | None:
    started = time.monotonic()
    created_at = datetime.now().isoformat(timespec="seconds")
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slice_stem = safe_name(f"{base_stem}_chunk{chunk_index:03d}_{int(start_s)}s")
    stream_work_dir = Path(args.stream_work_dir or STREAM_TMP_DIR)
    slice_path = stream_work_dir / f"{slice_stem}.mp4"
    print(f"Slicing {fmt_time(start_s)} + {fmt_time(duration_s)} -> {slice_path}")
    slice_url(url, start_s, duration_s, slice_path, headers)

    transcript = transcribe_audio(slice_path)
    if not transcript.get("segments"):
        slice_path.unlink(missing_ok=True)
        print(f"  [skip] chunk {chunk_index}: no speech detected, skipping output", flush=True)
        return None
    events, frames = extract_keyframes(slice_path)
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
) -> tuple[dict | None, ExtractedStream, dict]:
    current_stream = stream
    current_summary = source_summary
    recovery_errors: list[str] = []
    max_reextracts = max(0, args.reextract_retries) if args.page_url else 0
    reextract_count = 0

    while True:
        if keepalive:
            if not keepalive.is_browser_alive():
                raise BrowserDeadError("Playwright browser process is closed")
            try:
                current_stream = keepalive.latest_stream()
                current_stream.headers.update(overlay_headers(args))
            except Exception as e:
                raise BrowserDeadError(f"Playwright browser unresponsive: {e}") from e
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
                if keepalive and keepalive.is_stream_ended():
                    raise StreamEndedError("DOM confirms stream has ended") from e
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
                        if keepalive.is_stream_ended():
                            raise StreamEndedError("DOM confirms stream has ended")
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
                except StreamEndedError:
                    raise
                except Exception as refresh_error:
                    if is_ytdlp_stream_ended_error(refresh_error):
                        raise StreamEndedError(
                            f"yt-dlp reports stream offline: {refresh_error}"
                        ) from refresh_error
                    # greenlet.error surfaced through refresh_and_get() — browser died,
                    # stream has ended; convert to clean StreamEndedError so the run
                    # loop writes the final manifest and exits with code 0.
                    if "greenlet-stream-ended" in str(refresh_error):
                        raise StreamEndedError(
                            f"Playwright browser died during refresh — stream ended: {refresh_error}"
                        ) from refresh_error
                    if keepalive and keepalive.is_stream_ended():
                        raise StreamEndedError("DOM confirms stream has ended") from refresh_error
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
        f"- Mode: `{'live (ran until stream ended)' if data.get('live_mode') else 'fixed duration'}`",
        f"- Chunks: `{len(chunks)}`",
        f"- Processing elapsed sum: `{round(total_elapsed, 2)}` seconds",
        f"- Transcript segments: `{total_segments}`",
        f"- Transcript chars: `{total_chars}`",
        f"- Kept frames: `{total_frames}`",
        f"- Stream re-extractions: `{total_reextracts}`",
        f"- Slice files kept: `{kept_slices}/{len(chunks)}`",
    ]
    if data.get("stream_ended_reason"):
        lines.append(f"- Stream ended reason: `{data['stream_ended_reason']}`")
    lines.extend([
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
    ])
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


# ── Continuous HLS mode ──────────────────────────────────────────────────────
# Recorder runs ffmpeg in HLS segment mode continuously in a background thread.
# Consumer processes each completed .ts segment (ASR + keyframes) as it arrives.
# Recording never pauses for transcription — no gaps between segments.


class Recorder(threading.Thread):
    """ffmpeg HLS segmenter. Restarts with refreshed URL on expiry (up to max_restarts)."""

    def __init__(
        self,
        work_dir: Path,
        base_stem: str,
        seg_duration_s: int,
        keepalive: "PlaywrightKeepaliveStream | None",
        initial_stream: "ExtractedStream",
        max_restarts: int = MAX_BROWSER_RESTARTS,
    ) -> None:
        super().__init__(daemon=True, name="HLS-Recorder")
        self.work_dir = work_dir
        self._base = base_stem
        self._seg_s = seg_duration_s
        self._keepalive = keepalive
        self._stream = initial_stream
        self._max_restarts = max_restarts
        self._stop = threading.Event()
        self._ended = threading.Event()
        self._restart_count = 0
        self._end_error = ""

    def stop(self) -> None:
        self._stop.set()

    @property
    def is_stream_ended(self) -> bool:
        return self._ended.is_set()

    @property
    def end_error(self) -> str:
        return self._end_error

    def run(self) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        playlist = self.work_dir / f"{self._base}.m3u8"
        session_epoch = int(time.time())
        seg_pattern = str(self.work_dir / f"seg_{session_epoch}_%06d.ts")

        while not self._stop.is_set():
            if self._restart_count > self._max_restarts:
                self._end_error = f"exceeded {self._max_restarts} URL restarts"
                break

            cmd = [
                "ffmpeg", "-hide_banner", "-v", "warning",
                "-reconnect", "1", "-reconnect_streamed", "1",
                "-reconnect_on_network_error", "1", "-reconnect_delay_max", "10",
                "-i", self._stream.url,
                "-c", "copy",
                "-f", "hls",
                "-hls_time", str(self._seg_s),
                "-hls_flags", "temp_file+append_list+program_date_time",
                "-hls_segment_filename", seg_pattern,
                "-hls_list_size", "0",
                str(playlist),
                "-y",
            ]
            cmd = with_headers(cmd, self._stream.headers or {})

            print(f"[Recorder] Starting ffmpeg HLS (restart #{self._restart_count}, seg={self._seg_s}s)…")
            try:
                proc = subprocess.Popen(
                    cmd, cwd=str(ROOT_DIR),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace",
                )
                for raw in proc.stdout:
                    line = raw.rstrip()
                    if self._stop.is_set():
                        proc.kill()
                        break
                    if line:
                        print(f"[Recorder] {line}")
                    # Detect natural stream end from ffmpeg output
                    if any(t in line for t in ("End of file", "moov atom not found", "Invalid data")):
                        print(f"[Recorder] Stream ended: {line}")
                        self._ended.set()
                        proc.kill()
                        break
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except Exception:
                    pass
            except Exception as exc:
                self._end_error = f"Recorder subprocess error: {exc}"
                break

            if self._stop.is_set() or self._ended.is_set():
                break

            # ffmpeg exited unexpectedly — try URL refresh via keepalive
            if self._keepalive and self._restart_count < self._max_restarts:
                print("[Recorder] ffmpeg exited; refreshing URL via keepalive…")
                try:
                    self._stream = self._keepalive.latest_stream()
                    self._restart_count += 1
                    time.sleep(3.0)
                    continue
                except Exception as exc:
                    self._end_error = f"URL refresh failed: {exc}"
            self._ended.set()
            break

        self._ended.set()
        print(f"[Recorder] Stopped. restarts={self._restart_count} error={self._end_error!r}")


class Consumer(threading.Thread):
    """Processes completed HLS .ts segments produced by Recorder."""

    def __init__(
        self,
        work_dir: Path,
        base_stem: str,
        seg_duration_s: int,
        recorder: "Recorder",
        args: argparse.Namespace,
    ) -> None:
        super().__init__(daemon=True, name="HLS-Consumer")
        self.work_dir = work_dir
        self._base = base_stem
        self._seg_s = seg_duration_s
        self._recorder = recorder
        self._args = args
        self._chunks: list[dict] = []
        self._processed: set[str] = set()
        self._chunk_index = 0

    def get_chunks(self) -> list[dict]:
        return list(self._chunks)

    def run(self) -> None:
        poll_s = 3.0
        while True:
            ts_files = sorted(self.work_dir.glob("seg_*.ts"))
            # Don't process the last segment while recorder may still be writing it
            if not self._recorder.is_stream_ended and ts_files:
                ts_files = ts_files[:-1]

            new_files = [f for f in ts_files if f.name not in self._processed]
            for ts_path in new_files:
                self._chunk_index += 1
                start_s = float((self._chunk_index - 1) * self._seg_s)
                print(f"\n=== [Consumer] Chunk {self._chunk_index}: {fmt_time(start_s)} ===")
                chunk = self._process_ts(ts_path, start_s, self._chunk_index)
                self._processed.add(ts_path.name)
                if chunk is not None:
                    self._chunks.append(chunk)

            if self._recorder.is_stream_ended:
                # Drain any remaining unprocessed files
                for ts_path in sorted(self.work_dir.glob("seg_*.ts")):
                    if ts_path.name in self._processed:
                        continue
                    self._chunk_index += 1
                    start_s = float((self._chunk_index - 1) * self._seg_s)
                    chunk = self._process_ts(ts_path, start_s, self._chunk_index)
                    self._processed.add(ts_path.name)
                    if chunk is not None:
                        self._chunks.append(chunk)
                break

            time.sleep(poll_s)

        print(f"[Consumer] Done. {len(self._chunks)} chunks processed.")

    def _process_ts(self, ts_path: Path, start_s: float, chunk_index: int) -> dict | None:
        args = self._args
        started = time.monotonic()
        created_at = datetime.now().isoformat(timespec="seconds")
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        slice_stem = safe_name(f"{self._base}_chunk{chunk_index:03d}_{int(start_s)}s")

        transcript = transcribe_audio(ts_path)
        if not transcript.get("segments"):
            print(f"  [skip] chunk {chunk_index}: silent, skipping", flush=True)
            if args.cleanup_slices:
                ts_path.unlink(missing_ok=True)
            return None

        events, frames = extract_keyframes(ts_path)
        transcript_text = transcript_to_text(transcript)
        global_transcript_text = offset_transcript_text(transcript, start_s)
        payload = build_gemini_payload(ts_path.stem, transcript, events, frames)

        transcript_path = RUNS_DIR / f"stream-{slice_stem}-{timestamp}.transcript.txt"
        global_transcript_path = RUNS_DIR / f"stream-{slice_stem}-{timestamp}.global-transcript.txt"
        payload_path = RUNS_DIR / f"stream-{slice_stem}-{timestamp}.payload.json"
        report_path = RUNS_DIR / f"stream-{slice_stem}-{timestamp}.md"

        RUNS_DIR.mkdir(exist_ok=True)
        transcript_path.write_text(transcript_text, encoding="utf-8")
        global_transcript_path.write_text(global_transcript_text, encoding="utf-8")
        payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        slice_size = ts_path.stat().st_size
        if args.cleanup_slices:
            ts_path.unlink(missing_ok=True)

        data = {
            "created_at": created_at,
            "url_host": "hls-recorder",
            "extractor": "continuous-hls",
            "media_type": "hls-ts",
            "source": {"duration_s": self._seg_s, "size_bytes": slice_size,
                       "bit_rate": 0, "video": {}, "audio": {}},
            "auth_header_names": [],
            "slice": {"start_s": start_s, "duration_s": self._seg_s,
                      "path": str(ts_path), "size_bytes": slice_size,
                      "kept": not args.cleanup_slices},
            "processing": {
                "events": len(events), "frames": len(frames),
                "backend": transcript.get("backend_used"),
                "transcribe_duration_s": transcript.get("duration_s"),
                "segments": len(transcript.get("segments", [])),
                "transcript_chars": len(transcript_text),
                "elapsed_s": round(time.monotonic() - started, 2),
                "stream_reextracts": 0,
            },
            "recovery_errors": [],
            "outputs": {
                "transcript_txt": str(transcript_path),
                "payload_json": str(payload_path),
                "report_md": str(report_path),
                "global_transcript_txt": str(global_transcript_path),
            },
            "chunk": {"index": chunk_index, "total": 0},
            "transcript_preview": transcript_text[:1000],
            "global_transcript_preview": global_transcript_text[:1000],
            "global_transcript_text": global_transcript_text,
        }
        write_report(report_path, data)
        print(f"[Consumer] chunk {chunk_index} → {report_path.name} ({data['processing']['elapsed_s']}s)")
        return data


def _finalize_hls_run(
    chunks: list[dict],
    base_stem: str,
    created_at: str,
    stream: "ExtractedStream",
    ended_reason: str,
    args: argparse.Namespace,
) -> dict:
    """Write combined transcript + manifest for a finished HLS run."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    combined_text = "\n\n".join(
        Path(c["outputs"]["global_transcript_txt"]).read_text(encoding="utf-8")
        for c in chunks
        if Path(c["outputs"]["global_transcript_txt"]).exists()
    )
    combined_transcript_path = RUNS_DIR / f"stream-{base_stem}-{timestamp}.combined-transcript.txt"
    manifest_json_path = RUNS_DIR / f"stream-{base_stem}-{timestamp}.manifest.json"
    manifest_md_path = RUNS_DIR / f"stream-{base_stem}-{timestamp}.manifest.md"

    RUNS_DIR.mkdir(exist_ok=True)
    combined_transcript_path.write_text(combined_text, encoding="utf-8")

    seg_s = int(parse_time(getattr(args, "chunk_duration", None) or "60"))
    manifest = {
        "created_at": created_at,
        "url_host": urlparse(stream.url).hostname or "hls-recorder",
        "extractor": stream.extractor,
        "media_type": stream.media_type,
        "source": {"duration_s": len(chunks) * seg_s, "size_bytes": 0},
        "auth_header_names": sorted((stream.headers or {}).keys()),
        "start_s": 0,
        "duration_s": len(chunks) * seg_s,
        "live_mode": True,
        "capture_mode": "continuous-hls",
        "stream_ended_reason": ended_reason or "stream ended",
        "chunk_duration_s": seg_s,
        "chunks": chunks,
        "combined_transcript_path": str(combined_transcript_path),
    }
    manifest_json_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    write_manifest(manifest_md_path, manifest)
    print(f"\n[HLS] Manifest : {manifest_md_path}")
    print(f"[HLS] Transcript: {combined_transcript_path}")
    print(f"[HLS] Chunks   : {len(chunks)}")
    return manifest


def run_continuous_hls(args: argparse.Namespace) -> dict:
    """Live capture: Recorder (ffmpeg HLS) + Consumer (ASR+keyframes) run in parallel.

    Recording is never blocked by transcription — segments accumulate on disk while
    the previous segment is being processed. No gaps between segment boundaries.
    On URL expiry, Recorder refreshes via Playwright keepalive and restarts ffmpeg.
    Use --hls-consumer-only to drain a work_dir from a crashed previous run.
    """
    keepalive: PlaywrightKeepaliveStream | None = None
    try:
        if args.playwright_keepalive:
            keepalive, stream = start_keepalive_stream(args)
        else:
            stream = resolve_input(args)

        created_at = datetime.now().isoformat(timespec="seconds")
        seg_s = int(parse_time(args.chunk_duration or "60"))
        base_stem = safe_name(args.name or f"live_{int(time.time())}")
        work_dir = Path(args.stream_work_dir or STREAM_TMP_DIR) / base_stem
        work_dir.mkdir(parents=True, exist_ok=True)

        max_restarts = getattr(args, "max_browser_restarts", MAX_BROWSER_RESTARTS)
        recorder = Recorder(work_dir, base_stem, seg_s, keepalive, stream, max_restarts)
        consumer = Consumer(work_dir, base_stem, seg_s, recorder, args)

        print(f"[HLS] Work dir : {work_dir}")
        print(f"[HLS] Segment  : {seg_s}s per chunk")
        print(f"[HLS] Mode     : Recorder + Consumer (parallel)")
        print(f"[HLS] Max URL restarts: {max_restarts}")

        recorder.start()
        consumer.start()

        try:
            consumer.join()
        except KeyboardInterrupt:
            print("\n[HLS] Interrupted. Stopping recorder…")
            recorder.stop()
            recorder.join(timeout=20)
            consumer.join(timeout=60)

        recorder.stop()
        recorder.join(timeout=20)

        chunks = consumer.get_chunks()
        return _finalize_hls_run(chunks, base_stem, created_at, stream,
                                  recorder.end_error, args)
    finally:
        if keepalive:
            keepalive.close()


def run_hls_consumer_only(args: argparse.Namespace) -> dict:
    """Process existing .ts segments from a previous --continuous-hls run (crash recovery).

    Use --stream-work-dir to point at the directory containing seg_*.ts files.
    """
    work_dir = Path(args.stream_work_dir or STREAM_TMP_DIR)
    if not work_dir.exists():
        raise FileNotFoundError(f"HLS work dir not found: {work_dir}")

    ts_files = sorted(work_dir.glob("seg_*.ts"))
    if not ts_files:
        raise FileNotFoundError(f"No seg_*.ts files found in {work_dir}")

    print(f"[HLS consumer-only] Found {len(ts_files)} segments in {work_dir}")

    created_at = datetime.now().isoformat(timespec="seconds")
    seg_s = int(parse_time(args.chunk_duration or "60"))
    base_stem = safe_name(args.name or work_dir.name)

    # Minimal stub that reports stream as already ended
    class _EndedRecorder:
        is_stream_ended = True
        end_error = "consumer-only mode (no recorder)"
        def stop(self) -> None: pass  # noqa: E301

    consumer = Consumer(work_dir, base_stem, seg_s, _EndedRecorder(), args)  # type: ignore[arg-type]
    consumer.start()
    consumer.join()

    dummy_stream = ExtractedStream(
        url="", headers={}, extractor="hls-consumer-only",
        media_type="hls-ts", page_url="",
    )
    return _finalize_hls_run(consumer.get_chunks(), base_stem, created_at,
                              dummy_stream, "consumer-only replay", args)


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

        live_mode = requested_duration_s <= 0
        base_stem = safe_name(args.name or f"{host}_{int(start_s)}_{'live' if live_mode else int(requested_duration_s)}")
        if live_mode:
            chunk_count = args.max_chunks or 0
            print("Live mode: running until stream ends (no duration limit).")
        else:
            chunk_count = math.ceil(requested_duration_s / chunk_duration_s)
            if args.max_chunks:
                chunk_count = min(chunk_count, args.max_chunks)

        chunks: list[dict] = []
        stream_ended_reason = ""
        browser_restart_count = 0
        chunk_index = 0
        RUNS_DIR.mkdir(exist_ok=True)
        checkpoint_path = RUNS_DIR / f"stream-{base_stem}.checkpoint.json"

        while True:
            chunk_index += 1
            if chunk_count and chunk_index > chunk_count:
                break
            chunk_start = start_s + (chunk_index - 1) * chunk_duration_s
            if not live_mode:
                remaining = start_s + requested_duration_s - chunk_start
                if remaining <= 0:
                    break
                chunk_duration = min(chunk_duration_s, remaining)
            else:
                chunk_duration = chunk_duration_s
            total_label = f"/{chunk_count}" if chunk_count else "/∞"
            print(f"\n=== Chunk {chunk_index}{total_label}: {fmt_time(chunk_start)} + {fmt_time(chunk_duration)} ===")
            try:
                chunk, stream, source_summary = process_slice_with_recovery(
                    args,
                    stream,
                    source_summary,
                    base_stem,
                    chunk_start,
                    chunk_duration,
                    chunk_index,
                    chunk_count,
                    keepalive=keepalive,
                )
                url = stream.url
                headers = stream.headers
                host = urlparse(url).hostname or "unknown-host"
                if chunk is not None:
                    chunks.append(chunk)
                    if keepalive:
                        keepalive.mark_stream_active()
                    checkpoint_path.write_text(
                        json.dumps({"chunks": chunks, "created_at": created_at}, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
            except BrowserDeadError as e:
                max_restarts = args.max_browser_restarts
                if browser_restart_count >= max_restarts:
                    print(
                        f"\n{'=' * 60}\n"
                        f"[!] 浏览器已自动重启 {max_restarts} 次，仍无法恢复。\n"
                        f"    请手动检查直播页面是否正常，然后重新运行脚本。\n"
                        f"    已完成 {len(chunks)} 块，时间点: {fmt_time(chunk_start)}\n"
                        f"{'=' * 60}"
                    )
                    stream_ended_reason = (
                        f"browser dead after {max_restarts} restarts — manual intervention required"
                    )
                    break
                browser_restart_count += 1
                print(
                    f"\n  [!] 浏览器进程已关闭，尝试重启"
                    f" ({browser_restart_count}/{max_restarts})..."
                )
                try:
                    stream = keepalive.restart()
                    stream.headers.update(overlay_headers(args))
                    print(f"  浏览器重启成功，chunk {chunk_index} 将重试。")
                except Exception as restart_err:
                    print(f"  浏览器重启失败: {restart_err}")
                finally:
                    chunk_index -= 1  # 无论重启成败，下次循环仍重试同一块
            except StreamEndedError as e:
                stream_ended_reason = str(e)
                print(f"\n直播已结束: {stream_ended_reason}")
                break
            except StreamSliceError as e:
                print(f"\n[!] Chunk {chunk_index} 切片永久失败，保存已完成进度: {e}")
                stream_ended_reason = f"unrecoverable slice error at chunk {chunk_index}"
                break
            except KeyboardInterrupt:
                print("\n[!] 用户中断，保存已完成的进度...")
                stream_ended_reason = "user interrupted (Ctrl-C)"
                break

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
            "live_mode": live_mode,
            "stream_ended_reason": stream_ended_reason,
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
        checkpoint_path.unlink(missing_ok=True)
        print(f"\nManifest: {manifest_md_path}")
        print(f"Combined transcript: {combined_transcript_path}")

        if getattr(args, "gemini", False) and chunks:
            print("\n=== Gemini: Building notes document ===")
            try:
                from google import genai as _genai
                api_key = getattr(args, "gemini_api_key", "") or os.environ.get("GEMINI_API_KEY", "") or os.environ.get("OPENCLAW_GOOGLE_API_KEY", "")
                if not api_key:
                    print("[!] --gemini-api-key or GEMINI_API_KEY env var required — skipping Gemini")
                else:
                    client = _genai.Client(api_key=api_key)
                    parts = build_stream_gemini_parts(manifest)
                    result = _call_gemini_stream(client, parts, base_stem)
                    if result["text"]:
                        notes_path = RUNS_DIR / f"stream-{base_stem}-{timestamp}.notes.md"
                        notes_path.write_text(result["text"], encoding="utf-8")
                        manifest["notes_md_path"] = str(notes_path)
                        manifest_json_path.write_text(
                            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
                        )
                        print(
                            f"Notes: {notes_path} "
                            f"({len(result['text'])} chars, {result['gemini_calls']} Gemini calls)"
                        )
                    else:
                        print("[!] Gemini returned no text")
            except ImportError as e:
                print(f"[!] {e}")
            except Exception as e:
                print(f"[!] Gemini error: {e}")

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
        help=(
            "Total duration to capture. Use 0 for live mode: runs until the stream ends, "
            "the browser restarts 3 times, or Ctrl-C."
        ),
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
    parser.add_argument(
        "--max-browser-restarts",
        type=int,
        default=MAX_BROWSER_RESTARTS,
        help="Maximum browser auto-restarts in live mode before requiring manual intervention.",
    )
    parser.add_argument("--name", default="", help="Optional output stem.")
    parser.add_argument(
        "--gemini",
        action="store_true",
        help=(
            "After all chunks are processed, call Gemini to produce a "
            "NotebookLM-ready notes document (.notes.md). "
            "Requires GEMINI_API_KEY env var or --gemini-api-key."
        ),
    )
    parser.add_argument(
        "--gemini-api-key",
        default="",
        help="Gemini API key. Defaults to the GEMINI_API_KEY environment variable.",
    )
    # ── Continuous HLS flags ──────────────────────────────────────────────────
    parser.add_argument(
        "--continuous-hls",
        action="store_true",
        help=(
            "Continuous HLS recording mode: ffmpeg records .ts segments in a background "
            "thread while ASR + keyframe extraction runs in parallel. No gaps between "
            "segments. Recommended for unattended live streams."
        ),
    )
    parser.add_argument(
        "--hls-consumer-only",
        action="store_true",
        help=(
            "Process existing .ts segments from a previous --continuous-hls run "
            "without starting a new recording. "
            "Point --stream-work-dir at the directory containing seg_*.ts files."
        ),
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.hls_consumer_only:
        run_hls_consumer_only(args)
    elif args.continuous_hls:
        run_continuous_hls(args)
    else:
        run_validation(args)


if __name__ == "__main__":
    main()
