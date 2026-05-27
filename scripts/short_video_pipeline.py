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

PACK_MAX_VIDEOS = 8
PACK_MAX_TRANSCRIPT_CHARS = 80_000
PACK_MAX_FRAMES = 96
PER_VIDEO_MAX_FRAMES = 12
PACK_ESTIMATED_INPUT_TOKENS = 160_000
QWEN_MODEL = os.environ.get("QWEN_MODEL", "qwen3.6-flash")

# P3: CNY per million tokens (conservative DashScope public rates, <=256K context tier)
QWEN_PRICING: dict[str, dict[str, float]] = {
    "qwen3.6-flash": {"input_per_m": 1.2, "output_per_m": 7.2},
    "qwen-long": {"input_per_m": 0.5, "output_per_m": 2.0},
}
_QWEN_PRICING_DEFAULT = {"input_per_m": 1.2, "output_per_m": 7.2}

VIDEO_EXTENSIONS = {".mp4", ".webm", ".m4v", ".mov", ".avi", ".mkv", ".mpeg"}

# P2: per-video progress tracking (separate from long-video .progress.json)
SHORT_VIDEO_PROGRESS = DEFAULT_RUN_DIR / "short-video-progress.json"


def _default_sv_record(video_id: str) -> dict:
    return {
        "video_id": video_id,
        "preprocess_status": "pending",
        "synthesis_status": "pending",
        "classification": "",
        "pack_id": "",
        "provider": "",
        "api_calls": 0,
        "usage": {},
        "estimated_cost_cny": 0.0,
        "last_error": "",
    }


def load_sv_progress(progress_path: Path = SHORT_VIDEO_PROGRESS) -> dict:
    if not progress_path.exists():
        return {}
    try:
        data = json.loads(progress_path.read_text(encoding="utf-8"))
        return data.get("short_videos") or {}
    except Exception:
        return {}


def save_sv_progress(records: dict, progress_path: Path = SHORT_VIDEO_PROGRESS) -> None:
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if progress_path.exists():
        try:
            existing = json.loads(progress_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    existing["short_videos"] = records
    existing["updated_at"] = datetime.now().isoformat(timespec="seconds")
    progress_path.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def update_sv_video(
    video_id: str, updates: dict, progress_path: Path = SHORT_VIDEO_PROGRESS
) -> None:
    records = load_sv_progress(progress_path)
    record = records.get(video_id) or _default_sv_record(video_id)
    record.update(updates)
    records[video_id] = record
    save_sv_progress(records, progress_path)


def estimate_cost_cny(input_tokens: int, output_tokens: int, model: str = QWEN_MODEL) -> float:
    prices = QWEN_PRICING.get(model) or _QWEN_PRICING_DEFAULT
    return round(
        input_tokens / 1_000_000 * prices["input_per_m"]
        + output_tokens / 1_000_000 * prices["output_per_m"],
        6,
    )


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
    # Route by transcript volume, not duration.  PACK_MAX_TRANSCRIPT_CHARS is the
    # single boundary: videos at or below it are processed here (packed together or
    # as a solo one-shot call); videos above it go to the sliding-window pipeline
    # (build_stream_markdown.py).  duration_s and kept_frames are unused — the packer
    # caps per-video frames anyway and a 2000s+ video with a sparse transcript fits
    # in a single Qwen call just fine.
    if transcript_chars <= PACK_MAX_TRANSCRIPT_CHARS:
        return {
            "kind": "short_video",
            "reason": f"transcript<={PACK_MAX_TRANSCRIPT_CHARS}chars — packable or solo one-shot",
        }
    return {
        "kind": "long_or_dense_video",
        "reason": f"transcript>{PACK_MAX_TRANSCRIPT_CHARS}chars — route to sliding-window pipeline",
    }


def selected_frame_count(payload: dict, per_video_max_frames: int) -> int:
    return min(len(payload.get("frames") or []), per_video_max_frames)


def payload_to_item(payload_path: Path, payload: dict, limits: PackLimits) -> PackItem:
    source = payload.get("source") or {}
    media = payload.get("media") or {}
    transcript = payload.get("transcript") or {}
    frames = payload.get("frames") or []
    title = str(source.get("title") or payload.get("video_id") or payload_path.stem)
    transcript_chars = int(transcript.get("chars") or 0)
    duration_s = float(media.get("duration_s") or 0)
    # Recompute dynamically so existing payloads benefit from threshold changes
    recomputed_cls = classify_payload(duration_s, transcript_chars, len(frames))
    return PackItem(
        payload_path=payload_path,
        video_id=str(payload.get("video_id") or payload_path.stem),
        title=title,
        duration_s=duration_s,
        transcript_chars=transcript_chars,
        total_frames=len(frames),
        selected_frames=min(len(frames), limits.per_video_max_frames),
        classification=recomputed_cls["kind"],
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


def build_pack_plan(items: list[PackItem], limits: PackLimits) -> tuple[list[Pack], list[PackItem]]:
    candidates = [item for item in items if item.classification == "short_video"]
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
    # Primary: strict match requiring END_VIDEO_ID marker
    pattern = re.compile(
        r"<!--\s*VIDEO_ID:\s*([^>]+?)\s*-->(.*?)<!--\s*END_VIDEO_ID:\s*\1\s*-->",
        re.S,
    )
    blocks: dict[str, str] = {}
    for match in pattern.finditer(markdown_text):
        video_id = match.group(1).strip()
        blocks[video_id] = match.group(0).strip() + "\n"
    # Fallback: Qwen omits END_VIDEO_ID on single-video outputs; take content to
    # the next VIDEO_ID opener or EOF and synthesize a closing marker.
    fallback = re.compile(
        r"<!--\s*VIDEO_ID:\s*([^>]+?)\s*-->(.*?)(?=<!--\s*VIDEO_ID:|\Z)",
        re.S,
    )
    for match in fallback.finditer(markdown_text):
        video_id = match.group(1).strip()
        if video_id not in blocks:
            body = match.group(2).rstrip()
            blocks[video_id] = (
                f"<!-- VIDEO_ID: {video_id} -->{body}\n<!-- END_VIDEO_ID: {video_id} -->\n"
            )
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
    progress_path: Path = getattr(args, "progress", SHORT_VIDEO_PROGRESS)

    from zhihuTTS_video import (
        extract_keyframes,
        frame_marker,
        transcribe_audio_chunked,
        transcript_to_text,
        TRANSCRIBE_CHUNK_DURATION_S,
    )

    for index, source in enumerate(sources, 1):
        _src_path = None if is_url(source) else Path(source).expanduser()
        video_id = stable_video_id(source, _src_path)

        if getattr(args, "skip_done", False):
            rec = load_sv_progress(progress_path).get(video_id)
            if rec and rec.get("preprocess_status") == "done":
                print(f"[{index}/{len(sources)}] skip {video_id}")
                continue

        print(f"[{index}/{len(sources)}] preprocess {source}")
        try:
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
            update_sv_video(
                video_id,
                {"preprocess_status": "done", "classification": classification["kind"]},
                progress_path,
            )
        except Exception as exc:
            update_sv_video(video_id, {"preprocess_status": "failed", "last_error": str(exc)}, progress_path)
            print(f"  failed: {exc}", file=sys.stderr)
    return 0


def command_synthesize(args: argparse.Namespace) -> int:
    limits = PackLimits(
        max_videos=args.pack_max_videos,
        max_transcript_chars=args.pack_max_transcript_chars,
        max_frames=args.pack_max_frames,
        per_video_max_frames=args.per_video_max_frames,
    )
    items = load_payloads(args.payload_dir, limits)
    packs, deferred = build_pack_plan(items, limits)
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
    progress_path: Path = getattr(args, "progress", SHORT_VIDEO_PROGRESS)
    write_json(input_path, pack_input)

    force = getattr(args, "force", False)
    if not force and not args.mock_output and output_path.exists():
        print(f"Output already exists (use --force to re-call): {output_path}")
        result_meta = {"provider": "reused", "api_calls": 0, "finish_reason": "reused"}
    elif args.mock_output:
        text = build_mock_pack_output(pack_input)
        result_meta = {
            "provider": "mock",
            "api_calls": 0,
            "finish_reason": "mock",
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
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

        usage_dict = (result_meta.get("usage") or {})
        in_tok = int(usage_dict.get("input_tokens") or 0)
        out_tok = int(usage_dict.get("output_tokens") or 0)
        pack_cost = estimate_cost_cny(in_tok, out_tok, args.model)
        video_count = max(len(pack_input["videos"]), 1)
        cost_per_video = round(pack_cost / video_count, 6)

        for item in qc["videos"]:
            vid = item["video_id"]
            if item.get("markdown_path"):
                update_sv_video(
                    vid,
                    {
                        "synthesis_status": "done",
                        "pack_id": pack_input["pack_id"],
                        "provider": result_meta.get("provider", "qwen"),
                        "api_calls": int(result_meta.get("api_calls") or 0),
                        "usage": {k: v for k, v in result_meta.items()
                                  if k not in ("provider", "finish_reason")},
                        "estimated_cost_cny": cost_per_video,
                    },
                    progress_path,
                )
            else:
                update_sv_video(
                    vid,
                    {
                        "synthesis_status": "failed",
                        "pack_id": pack_input["pack_id"],
                        "last_error": "; ".join(item.get("warnings") or ["missing_video_id"]),
                    },
                    progress_path,
                )

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
    progress_path: Path = getattr(args, "progress", SHORT_VIDEO_PROGRESS)
    try:
        result = call_qwen_pack(retry_input, args)
        text = result.get("text") or ""
    except Exception as exc:
        err_str = str(exc)
        if "DataInspectionFailed" in err_str or "inappropriate content" in err_str.lower():
            print(f"  [retry] {video_id}: moderation blocked — {exc}", file=sys.stderr)
            update_sv_video(video_id, {"synthesis_status": "moderation_blocked",
                                       "last_error": f"DataInspectionFailed: {err_str[:200]}"}, progress_path)
        else:
            print(f"  [retry] {video_id}: call failed — {exc}", file=sys.stderr)
        return
    # Detect content moderation via empty response (no exception, but Qwen rejected the images)
    finish_reason = result.get("finish_reason") or ""
    if not text.strip() or "DataInspectionFailed" in finish_reason:
        reason = finish_reason or "empty response"
        print(f"  [retry] {video_id}: moderation blocked ({reason})", file=sys.stderr)
        update_sv_video(video_id, {"synthesis_status": "moderation_blocked",
                                   "last_error": f"DataInspectionFailed: {reason}"}, progress_path)
        return
    retry_output = pack_dir / f"{retry_pack_id}.output.md"
    retry_output.write_text(text, encoding="utf-8")
    qc = split_pack_output(retry_input, retry_output, args.markdowns_dir, args.qc_dir)
    usage_dict = (result.get("usage") or {})
    in_tok = int(usage_dict.get("input_tokens") or 0)
    out_tok = int(usage_dict.get("output_tokens") or 0)
    retry_cost = estimate_cost_cny(in_tok, out_tok, args.model)
    if qc["warnings"]:
        print(f"  [retry] {video_id}: still has warnings — {qc['warnings']}", file=sys.stderr)
        update_sv_video(video_id, {
            "synthesis_status": "failed",
            "pack_id": retry_pack_id,
            "last_error": "; ".join(qc["warnings"])[:200],
        }, progress_path)
    else:
        print(f"  [retry] {video_id}: ok → {args.markdowns_dir / ('TTS_short_' + slugify(video_id) + '.md')}")
        update_sv_video(video_id, {
            "synthesis_status": "done",
            "pack_id": retry_pack_id,
            "provider": result.get("provider", "qwen"),
            "api_calls": int(result.get("api_calls") or 0),
            "estimated_cost_cny": retry_cost,
        }, progress_path)


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


def command_retry_failed(args: argparse.Namespace) -> int:
    progress_path: Path = getattr(args, "progress", SHORT_VIDEO_PROGRESS)
    records = load_sv_progress(progress_path)

    retry_ids: set[str] = {
        vid for vid, rec in records.items()
        if rec.get("synthesis_status") in ("failed", "pending")
    }

    limits = PackLimits(
        max_videos=args.pack_max_videos,
        max_transcript_chars=args.pack_max_transcript_chars,
        max_frames=args.pack_max_frames,
        per_video_max_frames=args.per_video_max_frames,
    )

    all_items = load_payloads(args.payload_dir, limits)
    items = [item for item in all_items if item.video_id in retry_ids]

    if not items:
        print("No failed/pending videos with existing payloads.")
        return 0

    print(f"Retrying {len(items)} video(s):")
    for item in items:
        rec = records.get(item.video_id, {})
        err = (rec.get("last_error") or "")[:80]
        print(f"  {item.video_id}{': ' + err if err else ''}")

    packs, deferred = build_pack_plan(items, limits)
    plan_ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    plan = pack_plan_to_dict(packs, deferred, limits, plan_ts)
    print_pack_plan(plan)

    pack_dir = args.pack_dir
    plan_path = pack_dir / f"retry-{plan_ts}.plan.json"
    write_json(plan_path, plan)
    print(f"\nRetry plan: {plan_path}")
    print("Run each pack with:")
    for pack in plan["packs"]:
        print(
            f"  python scripts/short_video_pipeline.py call-pack "
            f"--plan {plan_path} --pack-id {pack['pack_id']} --split"
        )
    if deferred:
        print(f"\nDeferred ({len(deferred)} videos) — exceed pack limits, handle individually.")
    return 0


def command_report(args: argparse.Namespace) -> int:
    progress_path: Path = getattr(args, "progress", SHORT_VIDEO_PROGRESS)
    pack_dir: Path = args.pack_dir
    model: str = getattr(args, "model", QWEN_MODEL)
    records = load_sv_progress(progress_path)

    total = len(records)
    if total == 0:
        print("No progress records found.")
        return 0

    # Count as preprocessed if explicitly marked done OR if synthesis was attempted
    # (records created by call-pack don't carry preprocess_status)
    _synth_attempted = {"done", "failed", "moderation_blocked"}
    preprocess_done = sum(
        1 for r in records.values()
        if r.get("preprocess_status") == "done"
        or r.get("synthesis_status") in _synth_attempted
    )
    preprocess_failed = sum(1 for r in records.values() if r.get("preprocess_status") == "failed")
    synth_done = sum(1 for r in records.values() if r.get("synthesis_status") == "done")
    synth_failed = sum(1 for r in records.values() if r.get("synthesis_status") == "failed")
    synth_blocked = sum(1 for r in records.values() if r.get("synthesis_status") == "moderation_blocked")
    synth_pending = total - synth_done - synth_failed - synth_blocked

    # Aggregate tokens from pack manifests (authoritative source)
    total_input_tokens = 0
    total_output_tokens = 0
    pack_count = 0
    pack_costs: list[float] = []
    for manifest_path in sorted(pack_dir.glob("*.manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("schema_version") != "short-video-pack-call-v1":
                continue
            pack_count += 1
            inner = (manifest.get("usage") or {}).get("usage") or {}
            in_t = int(inner.get("input_tokens") or 0)
            out_t = int(inner.get("output_tokens") or 0)
            total_input_tokens += in_t
            total_output_tokens += out_t
            pack_costs.append(estimate_cost_cny(in_t, out_t, model))
        except Exception:
            continue

    total_cost = sum(pack_costs)

    print("Short-video Pipeline Report")
    print(f"  Progress file     : {progress_path}")
    print(f"  Model             : {model}")
    print(f"  Total videos      : {total}")
    print(f"  Preprocess done   : {preprocess_done} / {total}  (failed: {preprocess_failed})")
    print(f"  Synthesis done    : {synth_done} / {total}  (failed: {synth_failed}, blocked: {synth_blocked}, pending: {synth_pending})")
    print(f"  Pack manifests    : {pack_count}")
    print(f"  Total input tok   : {total_input_tokens:,}")
    print(f"  Total output tok  : {total_output_tokens:,}")
    if total_cost > 0:
        print(f"  Est. total (CNY)  : {total_cost:.4f}")
        if synth_done > 0:
            per_video = total_cost / synth_done
            calls_per_100 = pack_count / synth_done * 100
            print(f"  Cost/video        : {per_video:.6f} CNY")
            print(f"  Proj. 100 videos  : {per_video * 100:.4f} CNY  (~{calls_per_100:.1f} Qwen calls)")
        if pack_costs:
            print(f"  Avg cost/pack     : {total_cost / len(pack_costs):.4f} CNY")
    else:
        print("  Est. total (CNY)  : 0.000000  (no real Qwen calls yet)")
    return 0


def command_batch_export(args: argparse.Namespace) -> int:
    """Export pack inputs as DashScope Batch File API JSONL (schema draft)."""
    from utils import _parts_to_openai_messages  # internal helper, batch-export path only

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    packs = plan.get("packs") or []
    if not packs:
        print("No packs in plan.", file=sys.stderr)
        return 2

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_path = args.output or (args.pack_dir / f"batch-export-{ts}.jsonl")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    with output_path.open("w", encoding="utf-8") as f:
        for pack_def in packs:
            pack_input = build_pack_input(pack_def, args.per_video_max_frames)
            parts = build_qwen_pack_parts(pack_input)
            messages = _parts_to_openai_messages(parts)
            entry = {
                "custom_id": pack_input["pack_id"],
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": args.model,
                    "messages": messages,
                    "max_tokens": 64000,
                    "temperature": 0.1,
                },
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            written += 1

    print(f"Exported {written} pack(s) → {output_path}")
    print("DashScope Batch API submit steps:")
    print("  1. Upload JSONL : POST https://dashscope.aliyuncs.com/compatible-mode/v1/files")
    print("  2. Create batch : POST /v1/batches  {input_file_id, endpoint, completion_window}")
    print("  3. Poll status  : GET  /v1/batches/{batch_id}")
    print("  4. Retrieve out : GET  /v1/files/{output_file_id}/content")
    return 0


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
    long_items = [item for item in items if item.classification == "long_or_dense_video"]
    if long_items:
        print(f"\nlong_or_dense_video ({len(long_items)}) — transcript>{PACK_MAX_TRANSCRIPT_CHARS}chars, route to sliding-window:")
        for item in long_items:
            print(f"  {item.video_id}: {item.duration_s:.0f}s, {item.transcript_chars}chars, {item.total_frames}frames")
        print("  python scripts/build_stream_markdown.py --base <base> --synthesis-pass sliding-window")
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
    parser = argparse.ArgumentParser(description="Short-video Qwen pipeline (preprocess / synthesize / report / batch)")
    sub = parser.add_subparsers(dest="command", required=True)

    preprocess = sub.add_parser("preprocess", help="Generate short-video payloads; no LLM calls")
    preprocess.add_argument("--input-file", type=Path)
    preprocess.add_argument("--videos-dir", type=Path)
    preprocess.add_argument("--payload-dir", type=Path, default=DEFAULT_PAYLOAD_DIR)
    preprocess.add_argument("--download-dir", type=Path, default=DEFAULT_SHORT_VIDEO_DIR)
    preprocess.add_argument("--extractor", default="auto", choices=("auto", "direct", "ytdlp", "playwright"))
    preprocess.add_argument("--cookies-browser", default="")
    preprocess.add_argument("--skip-done", action="store_true", help="Skip videos already marked preprocess_status=done")
    preprocess.add_argument("--progress", type=Path, default=SHORT_VIDEO_PROGRESS)
    preprocess.set_defaults(func=command_preprocess)

    synthesize = sub.add_parser("synthesize", help="Build a Qwen pack plan")
    synthesize.add_argument("--payload-dir", type=Path, default=DEFAULT_PAYLOAD_DIR)
    synthesize.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK_DIR)
    synthesize.add_argument("--dry-run", action="store_true", help="No-op flag kept for backward compatibility")
    synthesize.add_argument("--write-plan", action="store_true", help="Write pack plan JSON")
    synthesize.add_argument("--plan-ts", default="")
    synthesize.add_argument("--short-only", action="store_true",
                            help="Deprecated no-op: classification is now transcript-based")
    synthesize.add_argument("--include-medium", action="store_true", default=False,
                            help="Deprecated no-op: all packable videos are included by default")
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
    call_pack.add_argument("--force", action="store_true", help="Re-call Qwen even if output.md already exists")
    call_pack.add_argument("--per-video-max-frames", type=int, default=PER_VIDEO_MAX_FRAMES)
    call_pack.add_argument("--progress", type=Path, default=SHORT_VIDEO_PROGRESS)
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

    retry_failed = sub.add_parser("retry-failed", help="Build a new pack plan for failed/pending videos")
    retry_failed.add_argument("--payload-dir", type=Path, default=DEFAULT_PAYLOAD_DIR)
    retry_failed.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK_DIR)
    retry_failed.add_argument("--include-medium", action="store_true")
    retry_failed.add_argument("--progress", type=Path, default=SHORT_VIDEO_PROGRESS)
    add_pack_limit_args(retry_failed)
    retry_failed.set_defaults(func=command_retry_failed)

    status = sub.add_parser("status", help="Summarize payload classifications")
    status.add_argument("--payload-dir", type=Path, default=DEFAULT_PAYLOAD_DIR)
    status.add_argument("--per-video-max-frames", type=int, default=PER_VIDEO_MAX_FRAMES)
    status.set_defaults(func=command_status)

    report = sub.add_parser("report", help="Aggregate usage, token counts, and cost estimates")
    report.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK_DIR)
    report.add_argument("--model", default=QWEN_MODEL)
    report.add_argument("--progress", type=Path, default=SHORT_VIDEO_PROGRESS)
    report.set_defaults(func=command_report)

    batch_export = sub.add_parser("batch-export", help="Export packs as DashScope Batch API JSONL (schema draft)")
    batch_export.add_argument("--plan", type=Path, required=True)
    batch_export.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK_DIR)
    batch_export.add_argument("--output", type=Path)
    batch_export.add_argument("--model", default=QWEN_MODEL)
    batch_export.add_argument("--per-video-max-frames", type=int, default=PER_VIDEO_MAX_FRAMES)
    batch_export.set_defaults(func=command_batch_export)

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
