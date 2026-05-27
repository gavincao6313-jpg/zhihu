from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]
# utils, zhihuTTS_video etc. live in repo root, not in scripts/
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_RUN_DIR = REPO_ROOT / "runs" / "short-video"
DEFAULT_PAYLOAD_DIR = DEFAULT_RUN_DIR / "preprocess"
DEFAULT_PACK_DIR = DEFAULT_RUN_DIR / "packs"
DEFAULT_QC_DIR = DEFAULT_RUN_DIR / "qc"
DEFAULT_MARKDOWNS_DIR = REPO_ROOT / "Markdowns"
DEFAULT_SHORT_VIDEO_DIR = REPO_ROOT / "Videos" / "short"

SCHEMA_VERSION = "short-video-payload-v1"
PACK_PLAN_VERSION = "short-video-pack-plan-v1"

SHORT_MAX_DURATION_S = 600
SHORT_MAX_TRANSCRIPT_CHARS = 12_000
SHORT_MAX_FRAMES = 32

MEDIUM_MAX_DURATION_S = 1_800
MEDIUM_MAX_TRANSCRIPT_CHARS = 40_000
MEDIUM_MAX_FRAMES = 128

PACK_MAX_VIDEOS = 8
PACK_MAX_TRANSCRIPT_CHARS = 80_000
PACK_MAX_FRAMES = 96
PER_VIDEO_MAX_FRAMES = 12
PACK_ESTIMATED_INPUT_TOKENS = 160_000
QWEN_MODEL = os.environ.get("QWEN_MODEL", "qwen3.6-flash")

VIDEO_EXTENSIONS = {".mp4", ".webm", ".m4v", ".mov", ".avi", ".mkv", ".mpeg"}

SHORT_VIDEO_PACK_PROMPT = """
你正在处理一个短视频包。每个 VIDEO_ID 都是一个独立视频，必须独立输出，禁止跨视频混写、合并、写“同上”。

你的目标是生成适合导入 NotebookLM 的中文 Markdown 源文档。不要写成短摘要；要保留逐字稿中的事实、数字、例子、观点、步骤、术语、提示词、代码/配置片段和可检索细节。

输出必须严格遵守以下 schema。每个视频必须有一组完整边界：

<!-- SHORT_VIDEO_PACK_ID: <pack_id> -->
<!-- VIDEO_ID: <video_id> -->
# <视频标题>

## 1. 内容概览

## 2. 时间线

### [00:00:00 - 00:00:15] <章节标题>

## 3. 关键事实

## 4. 可检索细节

## 5. 视觉证据索引

## 6. 完整逐字稿

<!-- END_VIDEO_ID: <video_id> -->

硬性要求：
- 每个输入视频必须输出 exactly one 个 VIDEO_ID 块。
- VIDEO_ID 必须与输入完全一致。
- 每个视频的完整逐字稿必须放入该视频自己的 `## 6. 完整逐字稿`。
- 如果某个视频信息不足，只能在该视频块内说明 `source_insufficient`，不能影响其他视频。
- 不要输出总文档，不要在所有视频外再总结。
""".strip()


@dataclass
class PackLimits:
    max_videos: int = PACK_MAX_VIDEOS
    max_transcript_chars: int = PACK_MAX_TRANSCRIPT_CHARS
    max_frames: int = PACK_MAX_FRAMES
    per_video_max_frames: int = PER_VIDEO_MAX_FRAMES
    estimated_input_tokens: int = PACK_ESTIMATED_INPUT_TOKENS


@dataclass
class PackItem:
    payload_path: Path
    video_id: str
    title: str
    duration_s: float
    transcript_chars: int
    total_frames: int
    selected_frames: int
    classification: str
    source_kind: str
    source_original: str
    score: int = field(init=False)

    def __post_init__(self) -> None:
        self.score = self.transcript_chars + self.selected_frames * 600


@dataclass
class Pack:
    index: int
    items: list[PackItem] = field(default_factory=list)

    @property
    def transcript_chars(self) -> int:
        return sum(item.transcript_chars for item in self.items)

    @property
    def selected_frames(self) -> int:
        return sum(item.selected_frames for item in self.items)

    def can_add(self, item: PackItem, limits: PackLimits) -> bool:
        return (
            len(self.items) < limits.max_videos
            and self.transcript_chars + item.transcript_chars <= limits.max_transcript_chars
            and self.selected_frames + item.selected_frames <= limits.max_frames
        )


def is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"}


def slugify(value: str, default: str = "video") -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return slug[:64] or default


def sha1_short(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def stable_video_id(source: str, local_path: Path | None = None) -> str:
    if is_url(source):
        parsed = urlparse(source)
        host = slugify(parsed.hostname or "url", "url")
        return f"{host}-{sha1_short(source)}"

    path = (local_path or Path(source)).expanduser()
    try:
        stat = path.stat()
        identity = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
    except OSError:
        identity = str(path)
    return f"{slugify(path.stem)}-{sha1_short(identity)}"


def read_sources(input_file: Path | None, videos_dir: Path | None) -> list[str]:
    sources: list[str] = []
    if input_file:
        for raw in input_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            sources.append(line)

    if videos_dir:
        for path in sorted(videos_dir.iterdir()):
            if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
                sources.append(str(path))

    deduped: list[str] = []
    seen: set[str] = set()
    for source in sources:
        key = source.strip()
        if key and key not in seen:
            deduped.append(key)
            seen.add(key)
    return deduped


def ffprobe_media(path: Path) -> dict:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration,size:stream=width,height",
        "-of", "json",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(proc.stdout or "{}")
    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    video_stream = next((s for s in streams if s.get("width") or s.get("height")), {})
    return {
        "duration_s": round(float(fmt.get("duration") or 0), 3),
        "width": int(video_stream.get("width") or 0),
        "height": int(video_stream.get("height") or 0),
        "size_bytes": int(float(fmt.get("size") or path.stat().st_size)),
    }


def resolve_url_to_video(source: str, output_dir: Path, extractor: str,
                         cookies_browser: str = "") -> tuple[Path, dict]:
    from stream_extractors import ExtractedStream, extract_stream, infer_media_type

    output_dir.mkdir(parents=True, exist_ok=True)
    video_id = stable_video_id(source)
    output_path = output_dir / f"{video_id}.mp4"
    if extractor == "direct":
        stream = ExtractedStream(
            url=source,
            headers={},
            extractor="direct",
            media_type=infer_media_type(source),
            page_url=source,
            title="",
        )
    else:
        stream = extract_stream(
            source,
            extractor=extractor,
            ytdlp_cookies_browser=cookies_browser,
        )
    headers_text = "".join(f"{key}: {value}\r\n" for key, value in stream.headers.items())

    cmd = ["ffmpeg", "-y"]
    if headers_text:
        cmd += ["-headers", headers_text]
    cmd += ["-i", stream.url, "-c", "copy", str(output_path)]
    subprocess.run(cmd, check=True)

    return output_path, {
        "kind": "url",
        "original": source,
        "canonical": stream.page_url or source,
        "resolved_media_url": stream.url,
        "local_media_path": str(output_path),
        "extractor": stream.extractor,
        "media_type": stream.media_type,
        "title": stream.title,
    }


def resolve_local_video(source: str) -> tuple[Path, dict]:
    path = Path(source).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Video not found: {path}")
    return path, {
        "kind": "file",
        "original": str(path),
        "canonical": str(path.resolve()),
        "resolved_media_url": "",
        "local_media_path": str(path),
        "extractor": "local",
        "media_type": path.suffix.lower().lstrip("."),
        "title": path.stem,
    }


def classify_payload(duration_s: float, transcript_chars: int, kept_frames: int) -> dict:
    if (
        duration_s <= SHORT_MAX_DURATION_S
        and transcript_chars <= SHORT_MAX_TRANSCRIPT_CHARS
        and kept_frames <= SHORT_MAX_FRAMES
    ):
        return {
            "kind": "short_video",
            "reason": "duration<=600, transcript_chars<=12000, kept_frames<=32",
        }
    if (
        duration_s <= MEDIUM_MAX_DURATION_S
        and transcript_chars <= MEDIUM_MAX_TRANSCRIPT_CHARS
        and kept_frames <= MEDIUM_MAX_FRAMES
    ):
        return {
            "kind": "medium_video",
            "reason": "within medium duration/transcript/frame thresholds",
        }
    return {
        "kind": "long_or_dense_video",
        "reason": "exceeds medium duration/transcript/frame thresholds",
    }


def selected_frame_count(payload: dict, per_video_max_frames: int) -> int:
    return min(len(payload.get("frames") or []), per_video_max_frames)


def payload_to_item(payload_path: Path, payload: dict, limits: PackLimits) -> PackItem:
    source = payload.get("source") or {}
    media = payload.get("media") or {}
    transcript = payload.get("transcript") or {}
    classification = payload.get("classification") or {}
    frames = payload.get("frames") or []
    title = str(source.get("title") or payload.get("video_id") or payload_path.stem)
    transcript_chars = int(transcript.get("chars") or 0)
    return PackItem(
        payload_path=payload_path,
        video_id=str(payload.get("video_id") or payload_path.stem),
        title=title,
        duration_s=float(media.get("duration_s") or 0),
        transcript_chars=transcript_chars,
        total_frames=len(frames),
        selected_frames=min(len(frames), limits.per_video_max_frames),
        classification=str(classification.get("kind") or "unknown"),
        source_kind=str(source.get("kind") or ""),
        source_original=str(source.get("original") or ""),
    )


def load_payloads(payload_dir: Path, limits: PackLimits) -> list[PackItem]:
    items: list[PackItem] = []
    for path in sorted(payload_dir.glob("*.payload.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != SCHEMA_VERSION:
            continue
        items.append(payload_to_item(path, payload, limits))
    return items


def build_pack_plan(items: list[PackItem], limits: PackLimits,
                    include_medium: bool = False) -> tuple[list[Pack], list[PackItem]]:
    candidates = [
        item for item in items
        if item.classification == "short_video" or (include_medium and item.classification == "medium_video")
    ]
    deferred = [item for item in items if item not in candidates]
    packs: list[Pack] = []

    for item in sorted(candidates, key=lambda x: (x.score, x.video_id), reverse=True):
        if (
            item.transcript_chars > limits.max_transcript_chars
            or item.selected_frames > limits.max_frames
        ):
            deferred.append(item)
            continue

        target = next((pack for pack in packs if pack.can_add(item, limits)), None)
        if target is None:
            target = Pack(index=len(packs) + 1)
            packs.append(target)
        target.items.append(item)

    return packs, sorted(deferred, key=lambda x: x.video_id)


def pack_plan_to_dict(packs: list[Pack], deferred: list[PackItem],
                      limits: PackLimits, plan_ts: str) -> dict:
    def item_dict(item: PackItem) -> dict:
        return {
            "video_id": item.video_id,
            "title": item.title,
            "classification": item.classification,
            "duration_s": item.duration_s,
            "transcript_chars": item.transcript_chars,
            "total_frames": item.total_frames,
            "selected_frames": item.selected_frames,
            "payload_path": str(item.payload_path),
            "source_kind": item.source_kind,
            "source_original": item.source_original,
        }

    return {
        "schema_version": PACK_PLAN_VERSION,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "plan_ts": plan_ts,
        "limits": {
            "max_videos": limits.max_videos,
            "max_transcript_chars": limits.max_transcript_chars,
            "max_frames": limits.max_frames,
            "per_video_max_frames": limits.per_video_max_frames,
            "estimated_input_tokens": limits.estimated_input_tokens,
        },
        "packs": [
            {
                "pack_id": f"pack-{plan_ts}-{pack.index:03d}",
                "video_count": len(pack.items),
                "transcript_chars": pack.transcript_chars,
                "selected_frames": pack.selected_frames,
                "items": [item_dict(item) for item in pack.items],
            }
            for pack in packs
        ],
        "deferred": [item_dict(item) for item in deferred],
        "summary": {
            "pack_count": len(packs),
            "packed_videos": sum(len(pack.items) for pack in packs),
            "deferred_videos": len(deferred),
            "estimated_qwen_calls": len(packs),
        },
    }


def print_pack_plan(plan: dict) -> None:
    summary = plan["summary"]
    print("Short-video Qwen pack dry-run")
    print(f"  packs              : {summary['pack_count']}")
    print(f"  packed videos      : {summary['packed_videos']}")
    print(f"  deferred videos    : {summary['deferred_videos']}")
    print(f"  estimated qwen calls: {summary['estimated_qwen_calls']}")
    for pack in plan["packs"]:
        print(
            f"\n{pack['pack_id']}: {pack['video_count']} videos, "
            f"{pack['transcript_chars']} chars, {pack['selected_frames']} frames"
        )
        for item in pack["items"]:
            print(
                f"  - {item['video_id']} "
                f"({item['duration_s']:.1f}s, {item['transcript_chars']} chars, "
                f"{item['selected_frames']}/{item['total_frames']} frames)"
            )
    if plan["deferred"]:
        print("\nDeferred:")
        for item in plan["deferred"]:
            print(f"  - {item['video_id']} [{item['classification']}]")


def load_pack_from_plan(plan_path: Path, pack_id: str = "", pack_index: int = 1) -> dict:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    packs = plan.get("packs") or []
    if pack_id:
        pack = next((p for p in packs if p.get("pack_id") == pack_id), None)
    else:
        pack = packs[pack_index - 1] if 0 <= pack_index - 1 < len(packs) else None
    if not pack:
        available = [p.get("pack_id") for p in packs]
        raise ValueError(f"Pack not found. Available: {available}")
    return pack


def load_payload_for_item(item: dict) -> dict:
    payload_path = Path(item["payload_path"])
    return json.loads(payload_path.read_text(encoding="utf-8"))


def read_transcript_text(payload: dict) -> str:
    path = Path((payload.get("transcript") or {}).get("path") or "")
    if path.exists():
        return path.read_text(encoding="utf-8")
    return str(payload.get("transcript_text") or "")


def choose_frame_records(payload: dict, max_frames: int) -> list[dict]:
    frames = list(payload.get("frames") or [])
    if len(frames) <= max_frames:
        return frames
    if max_frames <= 1:
        return frames[:1]
    step = (len(frames) - 1) / (max_frames - 1)
    indexes = sorted({round(i * step) for i in range(max_frames)})
    return [frames[i] for i in indexes if 0 <= i < len(frames)]


def build_pack_input(pack: dict, per_video_max_frames: int) -> dict:
    videos = []
    for item in pack.get("items") or []:
        payload = load_payload_for_item(item)
        transcript_text = read_transcript_text(payload)
        frame_records = choose_frame_records(payload, per_video_max_frames)
        source = payload.get("source") or {}
        media = payload.get("media") or {}
        videos.append({
            "video_id": item["video_id"],
            "title": item.get("title") or item["video_id"],
            "duration_s": media.get("duration_s") or item.get("duration_s"),
            "source": {
                "kind": source.get("kind") or item.get("source_kind"),
                "original": source.get("original") or item.get("source_original"),
                "local_media_path": source.get("local_media_path") or "",
            },
            "transcript_text": transcript_text,
            "transcript_chars": len(transcript_text),
            "frames": frame_records,
            "payload_path": item["payload_path"],
        })
    return {
        "schema_version": "short-video-pack-input-v1",
        "pack_id": pack["pack_id"],
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "video_count": len(videos),
        "videos": videos,
    }


class _InlineData:
    __slots__ = ("data", "mime_type")

    def __init__(self, data: bytes, mime_type: str) -> None:
        self.data = data
        self.mime_type = mime_type


class _Part:
    __slots__ = ("inline_data",)

    def __init__(self, inline_data: _InlineData) -> None:
        self.inline_data = inline_data


def build_qwen_pack_parts(pack_input: dict) -> list:
    parts: list = [SHORT_VIDEO_PACK_PROMPT]
    manifest_lines = [
        f"PACK_ID: {pack_input['pack_id']}",
        f"VIDEO_COUNT: {pack_input['video_count']}",
        "Required VIDEO_IDs: " + ", ".join(v["video_id"] for v in pack_input["videos"]),
    ]
    parts.append("\n".join(manifest_lines))

    for video in pack_input["videos"]:
        parts.append(
            "\n".join([
                "\n--- VIDEO START ---",
                f"VIDEO_ID: {video['video_id']}",
                f"TITLE: {video['title']}",
                f"DURATION_S: {video['duration_s']}",
                f"SOURCE: {video['source'].get('original', '')}",
                "TRANSCRIPT:",
                video["transcript_text"],
                "VISUAL_FRAMES:",
            ])
        )
        for frame in video["frames"]:
            marker = frame.get("marker") or f"Frame {frame.get('ts_s', '')}"
            parts.append(f"[VIDEO_ID={video['video_id']}] {marker}")
            frame_path = Path(frame.get("path") or "")
            if frame_path.exists():
                parts.append(_Part(_InlineData(frame_path.read_bytes(), "image/jpeg")))
            elif frame_path:
                parts.append(f"[frame_not_found] {frame_path}")
        parts.append("--- VIDEO END ---")
    return parts


def call_qwen_pack(pack_input: dict, args: argparse.Namespace) -> dict:
    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise EnvironmentError("DASHSCOPE_API_KEY is required for call-pack without --mock-output")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("openai package is required for Qwen calls. Run: pip install -r requirements.txt") from exc
    from utils import call_qwen

    client = OpenAI(
        api_key=api_key,
        base_url=os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    )
    result = call_qwen(
        client,
        build_qwen_pack_parts(pack_input),
        label=pack_input["pack_id"],
        model=args.model,
        enable_thinking=args.qwen_thinking,
        max_retries=args.max_retries,
        max_continuations=args.max_continuations,
    )
    return result


def build_mock_pack_output(pack_input: dict) -> str:
    lines = [f"<!-- SHORT_VIDEO_PACK_ID: {pack_input['pack_id']} -->"]
    for video in pack_input["videos"]:
        transcript = video["transcript_text"].strip()
        if not transcript:
            transcript = f"[00:00:00 - 00:00:10] Mock transcript for {video['video_id']}."
        excerpt = transcript[:500]
        lines.extend([
            f"<!-- VIDEO_ID: {video['video_id']} -->",
            f"# {video['title']}",
            "",
            "## 1. 内容概览",
            "",
            f"该短视频围绕 `{video['title']}` 展开，以下内容为 mock 输出，用于验证拆分和 QC。",
            "",
            "## 2. 时间线",
            "",
            "### [00:00:00 - 00:00:10] 开场与核心信息",
            "",
            excerpt,
            "",
            "## 3. 关键事实",
            "",
            f"- VIDEO_ID: `{video['video_id']}`",
            f"- duration_s: `{video['duration_s']}`",
            "",
            "## 4. 可检索细节",
            "",
            "- mock_detail: 用于离线验证 pack 输出 schema。",
            "",
            "## 5. 视觉证据索引",
            "",
            f"- selected_frames: {len(video['frames'])}",
            "",
            "## 6. 完整逐字稿",
            "",
            transcript,
            "",
            f"<!-- END_VIDEO_ID: {video['video_id']} -->",
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"


def extract_video_blocks(markdown_text: str) -> dict[str, str]:
    pattern = re.compile(
        r"<!--\s*VIDEO_ID:\s*([^>]+?)\s*-->(.*?)<!--\s*END_VIDEO_ID:\s*\1\s*-->",
        re.S,
    )
    blocks: dict[str, str] = {}
    for match in pattern.finditer(markdown_text):
        video_id = match.group(1).strip()
        blocks[video_id] = match.group(0).strip() + "\n"
    return blocks


def qc_video_block(video_id: str, block: str, expected: dict) -> dict:
    warnings: list[str] = []
    if not re.search(r"^#\s+\S+", block, re.M):
        warnings.append("missing_h1")
    required = ["## 1. 内容概览", "## 2. 时间线", "## 3. 关键事实", "## 4. 可检索细节", "## 6. 完整逐字稿"]
    missing = [section for section in required if section not in block]
    if missing:
        warnings.append("missing_sections: " + ", ".join(missing))
    if not re.search(r"###\s+\[\d{2}:\d{2}:\d{2}\s+-\s+\d{2}:\d{2}:\d{2}\]", block):
        warnings.append("missing_timestamped_timeline")
    body_chars = len(block)
    transcript_chars = int(expected.get("transcript_chars") or 0)
    if transcript_chars < 2000 and body_chars < 600:
        warnings.append("body_too_short_for_short_transcript")
    elif transcript_chars >= 2000 and body_chars / max(transcript_chars, 1) < 0.25:
        warnings.append("body_transcript_ratio_low")
    return {
        "video_id": video_id,
        "source_status": "full",
        "body_status": "ok" if not warnings else "warning",
        "transcript_chars": transcript_chars,
        "body_chars": body_chars,
        "body_transcript_ratio": round(body_chars / max(transcript_chars, 1), 4),
        "timeline_status": "ok" if not any("timeline" in w for w in warnings) else "warning",
        "warnings": warnings,
    }


def split_pack_output(pack_input: dict, output_md: Path, markdowns_dir: Path, qc_dir: Path) -> dict:
    markdown_text = output_md.read_text(encoding="utf-8")
    blocks = extract_video_blocks(markdown_text)
    expected = {video["video_id"]: video for video in pack_input["videos"]}
    markdowns_dir.mkdir(parents=True, exist_ok=True)
    qc_dir.mkdir(parents=True, exist_ok=True)

    video_qc = []
    warnings: list[str] = []
    for video_id, video in expected.items():
        block = blocks.get(video_id)
        if not block:
            warnings.append(f"missing_video_id: {video_id}")
            video_qc.append({
                "video_id": video_id,
                "source_status": "failed",
                "body_status": "failed",
                "warnings": ["missing_video_id"],
            })
            continue
        out_path = markdowns_dir / f"TTS_short_{slugify(video_id)}.md"
        out_path.write_text(block, encoding="utf-8")
        metrics = qc_video_block(video_id, block, video)
        metrics["markdown_path"] = str(out_path)
        video_qc.append(metrics)
        warnings.extend(f"{video_id}: {w}" for w in metrics["warnings"])

    extra = sorted(set(blocks) - set(expected))
    for video_id in extra:
        warnings.append(f"unexpected_video_id: {video_id}")

    qc = {
        "schema_version": "short-video-pack-qc-v1",
        "pack_id": pack_input["pack_id"],
        "output_md": str(output_md),
        "expected_video_count": len(expected),
        "parsed_video_count": len(blocks),
        "written_video_count": sum(1 for item in video_qc if item.get("markdown_path")),
        "warnings": warnings,
        "videos": video_qc,
    }
    qc_path = qc_dir / f"{pack_input['pack_id']}.qc.json"
    write_json(qc_path, qc)
    return qc


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def command_preprocess(args: argparse.Namespace) -> int:
    sources = read_sources(args.input_file, args.videos_dir)
    if not sources:
        print("No sources found. Use --input-file or --videos-dir.", file=sys.stderr)
        return 2

    payload_dir = args.payload_dir
    payload_dir.mkdir(parents=True, exist_ok=True)

    from zhihuTTS_video import (
        extract_keyframes,
        frame_marker,
        transcribe_audio_chunked,
        transcript_to_text,
        TRANSCRIBE_CHUNK_DURATION_S,
    )

    for index, source in enumerate(sources, 1):
        print(f"[{index}/{len(sources)}] preprocess {source}")
        if is_url(source):
            video_path, source_info = resolve_url_to_video(
                source,
                args.download_dir,
                extractor=args.extractor,
                cookies_browser=args.cookies_browser,
            )
            video_id = stable_video_id(source)
        else:
            video_path, source_info = resolve_local_video(source)
            video_id = stable_video_id(source, video_path)

        media = ffprobe_media(video_path)
        events, kept_frames = extract_keyframes(video_path)
        transcript = transcribe_audio_chunked(video_path, TRANSCRIBE_CHUNK_DURATION_S)
        transcript_text = transcript_to_text(transcript)

        transcript_path = payload_dir / f"{video_id}.transcript.txt"
        frames_path = payload_dir / f"{video_id}.frames.json"
        payload_path = payload_dir / f"{video_id}.payload.json"
        transcript_path.write_text(transcript_text, encoding="utf-8")

        frame_records = [
            {
                "path": str(path),
                "marker": frame_marker(path, events),
            }
            for path in kept_frames
        ]
        write_json(frames_path, {"video_id": video_id, "frames": frame_records, "events": events})

        classification = classify_payload(media["duration_s"], len(transcript_text), len(frame_records))
        payload = {
            "schema_version": SCHEMA_VERSION,
            "video_id": video_id,
            "source": source_info,
            "media": media,
            "transcript": {
                "backend": transcript.get("backend_used") or "",
                "chars": len(transcript_text),
                "path": str(transcript_path),
            },
            "frames": frame_records,
            "classification": classification,
        }
        write_json(payload_path, payload)
        print(
            f"  wrote {payload_path} [{classification['kind']}] "
            f"{len(transcript_text)} chars, {len(frame_records)} frames"
        )
    return 0


def command_synthesize(args: argparse.Namespace) -> int:
    if not args.dry_run:
        print("P0 only supports synthesize --dry-run. Real Qwen calls are P1.", file=sys.stderr)
        return 2

    limits = PackLimits(
        max_videos=args.pack_max_videos,
        max_transcript_chars=args.pack_max_transcript_chars,
        max_frames=args.pack_max_frames,
        per_video_max_frames=args.per_video_max_frames,
    )
    items = load_payloads(args.payload_dir, limits)
    if args.short_only:
        items = [item for item in items if item.classification == "short_video"]
    packs, deferred = build_pack_plan(items, limits, include_medium=args.include_medium)
    plan_ts = args.plan_ts or datetime.now().strftime("%Y%m%d-%H%M%S")
    plan = pack_plan_to_dict(packs, deferred, limits, plan_ts)
    print_pack_plan(plan)

    if args.write_plan:
        plan_path = args.pack_dir / f"pack-{plan_ts}.plan.json"
        write_json(plan_path, plan)
        print(f"\nPlan written: {plan_path}")
    return 0


def command_call_pack(args: argparse.Namespace) -> int:
    pack = load_pack_from_plan(args.plan, args.pack_id, args.pack_index)
    pack_input = build_pack_input(pack, args.per_video_max_frames)
    pack_dir = args.pack_dir
    input_path = pack_dir / f"{pack_input['pack_id']}.input.json"
    output_path = args.output_md or (pack_dir / f"{pack_input['pack_id']}.output.md")
    write_json(input_path, pack_input)

    if args.mock_output:
        text = build_mock_pack_output(pack_input)
        result_meta = {
            "provider": "mock",
            "api_calls": 0,
            "finish_reason": "mock",
        }
    else:
        try:
            result = call_qwen_pack(pack_input, args)
        except Exception as exc:
            print(f"call-pack failed: {exc}", file=sys.stderr)
            return 1
        text = result.get("text") or ""
        result_meta = {key: value for key, value in result.items() if key != "text"}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")

    manifest = {
        "schema_version": "short-video-pack-call-v1",
        "pack_id": pack_input["pack_id"],
        "input_path": str(input_path),
        "output_path": str(output_path),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "provider": result_meta.get("provider", "qwen"),
        "model": args.model,
        "usage": result_meta,
        "video_ids": [video["video_id"] for video in pack_input["videos"]],
    }
    manifest_path = pack_dir / f"{pack_input['pack_id']}.manifest.json"
    write_json(manifest_path, manifest)
    print(f"Pack input   : {input_path}")
    print(f"Pack output  : {output_path}")
    print(f"Manifest     : {manifest_path}")

    if args.split:
        qc = split_pack_output(pack_input, output_path, args.markdowns_dir, args.qc_dir)
        print(f"Split videos : {qc['written_video_count']}/{qc['expected_video_count']}")
        print(f"QC warnings  : {len(qc['warnings'])}")

        missing_ids = [
            w[len("missing_video_id: "):]
            for w in qc["warnings"]
            if w.startswith("missing_video_id: ")
        ]
        if missing_ids and not args.mock_output:
            print(f"Retrying {len(missing_ids)} missing video(s)...")
            for vid in missing_ids:
                _retry_missing_video(vid, pack_input, args, pack_dir)
    return 0


def _retry_missing_video(
    video_id: str,
    pack_input: dict,
    args: argparse.Namespace,
    pack_dir: Path,
) -> None:
    single = next((v for v in pack_input["videos"] if v["video_id"] == video_id), None)
    if not single:
        print(f"  [retry] video_id not in pack_input: {video_id}", file=sys.stderr)
        return
    retry_pack_id = f"{pack_input['pack_id']}-retry-{slugify(video_id)}"
    retry_input = {
        "schema_version": pack_input["schema_version"],
        "pack_id": retry_pack_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "video_count": 1,
        "videos": [single],
    }
    try:
        result = call_qwen_pack(retry_input, args)
        text = result.get("text") or ""
    except Exception as exc:
        print(f"  [retry] {video_id}: call failed — {exc}", file=sys.stderr)
        return
    retry_output = pack_dir / f"{retry_pack_id}.output.md"
    retry_output.write_text(text, encoding="utf-8")
    qc = split_pack_output(retry_input, retry_output, args.markdowns_dir, args.qc_dir)
    if qc["warnings"]:
        print(f"  [retry] {video_id}: still has warnings — {qc['warnings']}", file=sys.stderr)
    else:
        print(f"  [retry] {video_id}: ok → {args.markdowns_dir / ('TTS_short_' + slugify(video_id) + '.md')}")


def command_split_pack(args: argparse.Namespace) -> int:
    if args.input_json:
        pack_input = json.loads(args.input_json.read_text(encoding="utf-8"))
    else:
        if not args.plan:
            print("split-pack requires --input-json or --plan", file=sys.stderr)
            return 2
        pack = load_pack_from_plan(args.plan, args.pack_id, args.pack_index)
        pack_input = build_pack_input(pack, args.per_video_max_frames)
    qc = split_pack_output(pack_input, args.output_md, args.markdowns_dir, args.qc_dir)
    print(f"Split videos : {qc['written_video_count']}/{qc['expected_video_count']}")
    print(f"QC path      : {args.qc_dir / (pack_input['pack_id'] + '.qc.json')}")
    if qc["warnings"]:
        for warning in qc["warnings"]:
            print(f"  [warn] {warning}")
    return 0 if not qc["warnings"] else 1


def command_status(args: argparse.Namespace) -> int:
    limits = PackLimits(per_video_max_frames=args.per_video_max_frames)
    items = load_payloads(args.payload_dir, limits)
    counts: dict[str, int] = {}
    for item in items:
        counts[item.classification] = counts.get(item.classification, 0) + 1
    print(f"Payload dir: {args.payload_dir}")
    print(f"Payloads   : {len(items)}")
    for key in sorted(counts):
        print(f"  {key}: {counts[key]}")
    return 0


def command_mock_payloads(args: argparse.Namespace) -> int:
    args.payload_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, args.count + 1):
        video_id = f"mock-short-{i:03d}"
        duration_s = 45 + (i * 37) % 520
        transcript_chars = 900 + (i * 1379) % 10_500
        frame_count = 4 + (i * 5) % 28
        transcript_path = args.payload_dir / f"{video_id}.transcript.txt"
        transcript_path.write_text(
            (f"[00:00:00 - 00:00:10] Mock transcript for {video_id}.\n" * 10),
            encoding="utf-8",
        )
        frames = [
            {
                "ts_s": j * max(1, duration_s // max(frame_count, 1)),
                "type": "slide" if j % 3 == 0 else "context",
                "path": f"/mock/{video_id}/frame_{j:05d}.jpg",
                "marker": f"Frame [00:00:{j:02d}] type=mock",
            }
            for j in range(frame_count)
        ]
        payload = {
            "schema_version": SCHEMA_VERSION,
            "video_id": video_id,
            "source": {
                "kind": "mock",
                "original": f"mock://{video_id}",
                "canonical": f"mock://{video_id}",
                "resolved_media_url": "",
                "local_media_path": "",
                "extractor": "mock",
                "media_type": "mp4",
                "title": video_id,
            },
            "media": {
                "duration_s": duration_s,
                "width": 1920,
                "height": 1080,
                "size_bytes": 10_000_000 + i,
            },
            "transcript": {
                "backend": "mock",
                "chars": transcript_chars,
                "path": str(transcript_path),
            },
            "frames": frames,
            "classification": classify_payload(duration_s, transcript_chars, frame_count),
        }
        write_json(args.payload_dir / f"{video_id}.payload.json", payload)
    print(f"Wrote {args.count} mock payloads to {args.payload_dir}")
    return 0


def add_pack_limit_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--pack-max-videos", type=int, default=PACK_MAX_VIDEOS)
    parser.add_argument("--pack-max-transcript-chars", type=int, default=PACK_MAX_TRANSCRIPT_CHARS)
    parser.add_argument("--pack-max-frames", type=int, default=PACK_MAX_FRAMES)
    parser.add_argument("--per-video-max-frames", type=int, default=PER_VIDEO_MAX_FRAMES)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="P0 short-video Qwen pipeline planner")
    sub = parser.add_subparsers(dest="command", required=True)

    preprocess = sub.add_parser("preprocess", help="Generate short-video payloads; no LLM calls")
    preprocess.add_argument("--input-file", type=Path)
    preprocess.add_argument("--videos-dir", type=Path)
    preprocess.add_argument("--payload-dir", type=Path, default=DEFAULT_PAYLOAD_DIR)
    preprocess.add_argument("--download-dir", type=Path, default=DEFAULT_SHORT_VIDEO_DIR)
    preprocess.add_argument("--extractor", default="auto", choices=("auto", "direct", "ytdlp", "playwright"))
    preprocess.add_argument("--cookies-browser", default="")
    preprocess.set_defaults(func=command_preprocess)

    synthesize = sub.add_parser("synthesize", help="Build a Qwen pack plan")
    synthesize.add_argument("--payload-dir", type=Path, default=DEFAULT_PAYLOAD_DIR)
    synthesize.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK_DIR)
    synthesize.add_argument("--dry-run", action="store_true", help="Required in P0; do not call Qwen")
    synthesize.add_argument("--write-plan", action="store_true", help="Write pack plan JSON")
    synthesize.add_argument("--plan-ts", default="")
    synthesize.add_argument("--short-only", action="store_true")
    synthesize.add_argument("--include-medium", action="store_true")
    add_pack_limit_args(synthesize)
    synthesize.set_defaults(func=command_synthesize)

    call_pack = sub.add_parser("call-pack", help="Call Qwen for one pack, or generate mock output")
    call_pack.add_argument("--plan", type=Path, required=True, help="Pack plan JSON from synthesize --write-plan")
    call_pack.add_argument("--pack-id", default="")
    call_pack.add_argument("--pack-index", type=int, default=1)
    call_pack.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK_DIR)
    call_pack.add_argument("--output-md", type=Path)
    call_pack.add_argument("--markdowns-dir", type=Path, default=DEFAULT_MARKDOWNS_DIR)
    call_pack.add_argument("--qc-dir", type=Path, default=DEFAULT_QC_DIR)
    call_pack.add_argument("--model", default=QWEN_MODEL)
    call_pack.add_argument("--max-retries", type=int, default=2)
    call_pack.add_argument("--max-continuations", type=int, default=1)
    call_pack.add_argument("--qwen-thinking", action="store_true")
    call_pack.add_argument("--mock-output", action="store_true", help="Do not call Qwen; write deterministic mock Markdown")
    call_pack.add_argument("--split", action="store_true", help="Split output into per-video Markdown after call")
    call_pack.add_argument("--per-video-max-frames", type=int, default=PER_VIDEO_MAX_FRAMES)
    call_pack.set_defaults(func=command_call_pack)

    split_pack = sub.add_parser("split-pack", help="Split pack output Markdown into per-video files")
    split_pack.add_argument("--output-md", type=Path, required=True)
    split_pack.add_argument("--plan", type=Path, help="Pack plan JSON")
    split_pack.add_argument("--input-json", type=Path, help="Pack input JSON written by call-pack")
    split_pack.add_argument("--pack-id", default="")
    split_pack.add_argument("--pack-index", type=int, default=1)
    split_pack.add_argument("--markdowns-dir", type=Path, default=DEFAULT_MARKDOWNS_DIR)
    split_pack.add_argument("--qc-dir", type=Path, default=DEFAULT_QC_DIR)
    split_pack.add_argument("--per-video-max-frames", type=int, default=PER_VIDEO_MAX_FRAMES)
    split_pack.set_defaults(func=command_split_pack)

    status = sub.add_parser("status", help="Summarize payload classifications")
    status.add_argument("--payload-dir", type=Path, default=DEFAULT_PAYLOAD_DIR)
    status.add_argument("--per-video-max-frames", type=int, default=PER_VIDEO_MAX_FRAMES)
    status.set_defaults(func=command_status)

    mock = sub.add_parser("mock-payloads", help="Create mock payloads for offline pack-plan tests")
    mock.add_argument("--payload-dir", type=Path, default=DEFAULT_PAYLOAD_DIR)
    mock.add_argument("--count", type=int, default=20)
    mock.set_defaults(func=command_mock_payloads)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
