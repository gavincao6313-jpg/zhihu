"""Post-stream LLM synthesis: assemble all live chunks → NotebookLM document.

Run after zhihuTTS_stream.py finishes and merge_stream_chunks.py has produced
the raw merged transcript. This script:
  1. Loads all per-chunk global-transcript.txt → combined full transcript
  2. Loads all per-chunk payload.json → all keyframe images, globally sorted
  3. Calls Gemini/Qwen with the full prompt + selected frames
  4. Writes a NotebookLM-ready document to Markdowns/TTS_stream-<base>[-label].md

Requires GEMINI_API_KEY / OPENCLAW_GOOGLE_API_KEY for Gemini, or
DASHSCOPE_API_KEY for Qwen.

Usage (Windows):
    set GEMINI_API_KEY=your_key
    python scripts\\build_stream_markdown.py --base zhihu-gaowei-20260518 --provider gemini

Usage (Mac/Linux):
    DASHSCOPE_API_KEY=your_key python scripts/build_stream_markdown.py --base zhihu-gaowei-20260518 --provider qwen

Options:
    --base          Stream base name (required). Matches stream-{base}_chunk* files.
    --runs-dir      Directory with per-chunk files (default: runs)
    --markdowns-dir Output directory for NotebookLM document (default: Markdowns)
    --run-ts        Use a specific run timestamp YYYYMMDD-HHMMSS (default: latest run)
    --dry-run       Print QC and provider budget without calling the model API
    --max-frames N  Optional provider-neutral image cap for fair A/B tests
    --mock-gemini-text FILE
                    Offline validation only: use FILE as provider output and write final Markdown
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

try:
    from google import genai
    from google.genai import types
    _GENAI_AVAILABLE = True
except ImportError:
    genai = None  # type: ignore[assignment]
    types = None  # type: ignore[assignment]
    _GENAI_AVAILABLE = False

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils import call_gemini, call_qwen, extract_run_ts, fmt_ts

# ── Provider config ───────────────────────────────────────────────────────────

GEMINI_MODEL            = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
QWEN_MODEL              = os.environ.get("QWEN_MODEL", "qwen3.6-flash")
GEMINI_IMAGE_HARD_LIMIT = 3000   # API ceiling; fallback priority sampling above this
QWEN_IMAGE_HARD_LIMIT   = 250
QWEN_DEFAULT_MAX_FRAMES = 128
MAX_RETRIES             = 2      # Gemini quota guard: keep automatic retries small
MAX_CONTINUATIONS       = 2      # Gemini quota guard: 1 initial + 2 continuation calls max
RETRY_DELAY             = 65

# ── P0 QC config ──────────────────────────────────────────────────────────────

GAP_THRESHOLD_S     = 30    # seconds above typical chunk interval → counts as a gap
SILENT_CHARS_LIMIT  = 10    # transcript chars below this → silent chunk
TAIL_COVERAGE_RATIO = 0.85  # transcript must reach ≥ 85% of estimated stream end
BODY_COVERAGE_GAP_S = 120   # warn if last Markdown chapter ends >2 min before stream end

GEMINI_PROMPT_TEXT = """
# 角色与目标
你是一个顶级的知识库数据提取专家。我将提供一段视频的**完整逐字稿（带时间戳）**和**关键帧截图（包含幻灯片切换和画笔标注）**，请将它们视为完整的视频内容，提取转化为一份**高度详尽、结构化、完全适合导入 NotebookLM 作为底层语料的 Markdown 文档**。

# 背景信息（重要）
本视频是一场中文AI技术直播课/讲座，内容通常涉及大语言模型（LLM）、RAG（检索增强生成）、MCP（Model Context Protocol）、Agent、Claude、Cursor、ComfyUI、SenseVoice、FunASR 等AI开发工具和技术。请优先识别并准确保留这些专业术语原文，不要翻译或通俗化处理。

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
由于视频信息量极大，请保持极高的专注度，不要省略中间章节。如果你的输出达到了字数上限，请停在当前完整的段落，我会回复"继续"，你再接着上文输出。
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_chunk_start(path: Path) -> int:
    """Extract global start_s from filename: stream-base_chunk001_120s-ts.ext → 120"""
    m = re.search(r'_chunk\d+_(\d+)s[-.]', path.name)
    return int(m.group(1)) if m else 0


# ── Data loading ──────────────────────────────────────────────────────────────

def build_combined_transcript(chunk_files: list[Path]) -> str:
    """Concatenate per-chunk global-transcript.txt files in chronological order."""
    parts = []
    for cf in chunk_files:
        if cf.exists():
            text = cf.read_text(encoding="utf-8").strip()
            if text:
                parts.append(text)
    return "\n".join(parts)


def load_chunk_frames(payload_path: Path, chunk_start_s: int) -> list[dict]:
    """Load frames from a per-chunk payload.json, adjusting timestamps to global seconds."""
    if not payload_path.exists():
        return []
    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    result = []
    for f in payload.get("frames", []):
        local_ts  = f.get("timestamp_s", 0)
        global_ts = chunk_start_s + local_ts

        # Rewrite marker display timestamp from local to global
        marker = f.get("marker", "")
        if marker:
            marker = re.sub(
                r'Frame \[\d+:\d+:\d+\]',
                f'Frame [{fmt_ts(global_ts)}]',
                marker,
            )

        result.append({
            "path":        f.get("path", ""),
            "timestamp_s": global_ts,
            "marker":      marker,
        })
    return result


def collect_all_frames(chunk_files: list[Path]) -> list[dict]:
    """Assemble all keyframes from all chunks, sorted by global timestamp."""
    all_frames: list[dict] = []
    for cf in chunk_files:
        chunk_start_s = parse_chunk_start(cf)
        payload_path  = cf.with_name(
            cf.name.removesuffix(".global-transcript.txt") + ".payload.json"
        )
        all_frames.extend(load_chunk_frames(payload_path, chunk_start_s))
    all_frames.sort(key=lambda f: f.get("timestamp_s", 0))
    return all_frames


# ── Provider input assembly ───────────────────────────────────────────────────

def select_frames(frames: list[dict], *, image_limit: int = GEMINI_IMAGE_HARD_LIMIT) -> list[dict]:
    """Return selected frames, prioritizing slides/annotations when over limit."""
    if image_limit <= 0:
        return []
    if len(frames) <= image_limit:
        return frames

    slide_frames = [f for f in frames if "type=slide"      in f.get("marker", "")]
    annot_frames = [f for f in frames if "type=annotation" in f.get("marker", "")]
    ctx_frames   = [f for f in frames
                    if "type=slide"      not in f.get("marker", "")
                    and "type=annotation" not in f.get("marker", "")]

    cap      = image_limit
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
    return selected


def build_gemini_parts(
    transcript: str,
    frames: list[dict],
    *,
    provider: str = "gemini",
    image_limit: int = GEMINI_IMAGE_HARD_LIMIT,
) -> tuple[list, dict]:
    selected    = select_frames(frames, image_limit=image_limit)
    slide_count = sum(1 for f in selected if "type=slide"      in f.get("marker", ""))
    annot_count = sum(1 for f in selected if "type=annotation" in f.get("marker", ""))

    parts: list = [GEMINI_PROMPT_TEXT, transcript]
    loaded = 0
    for frame in selected:
        fp = Path(frame["path"])
        if not fp.exists():
            continue
        parts.append(frame.get("marker", f"Frame [{fmt_ts(frame.get('timestamp_s', 0))}]"))
        img_data = fp.read_bytes()
        if _GENAI_AVAILABLE:
            parts.append(types.Part(
                inline_data=types.Blob(mime_type="image/jpeg", data=img_data)
            ))
        else:
            from types import SimpleNamespace as _NS
            parts.append(_NS(inline_data=_NS(data=img_data, mime_type="image/jpeg")))
        loaded += 1

    frame_policy = {
        "provider": provider,
        "total_frames": len(frames),
        "selected_frames": loaded,
        "dropped_frames": max(0, len(frames) - loaded),
        "cap": image_limit,
        "slide_frames": slide_count,
        "annotation_frames": annot_count,
    }
    print(f"  {provider} parts: transcript {len(transcript):,} chars, "
          f"{loaded}/{len(frames)} frames (slide={slide_count}, annot={annot_count}, cap={image_limit})",
          flush=True)
    return parts, frame_policy


# ── P0 QC ─────────────────────────────────────────────────────────────────────

def live_final_qc(
    chunk_files: list[Path],
    transcript: str,
    all_frames: list[dict],
    base: str,
    selected_ts: str,
) -> dict:
    """Build a quality manifest from per-chunk files before Gemini synthesis.

    Reads chunk filenames and transcript files only; does NOT call Gemini.
    """
    starts = [parse_chunk_start(cf) for cf in chunk_files]

    # Typical inter-chunk interval (median) — used for gap detection and timeline estimate
    if len(starts) >= 2:
        intervals     = sorted(starts[i + 1] - starts[i] for i in range(len(starts) - 1))
        typical_ivl_s = intervals[len(intervals) // 2]
    else:
        typical_ivl_s = 60

    first_timestamp_s   = starts[0] if starts else 0
    timeline_end_s      = (starts[-1] + typical_ivl_s) if starts else 0
    timeline_duration_s = timeline_end_s - first_timestamp_s

    # Per-chunk silent / failed counts
    silent_chunk_count = 0
    failed_chunk_count = 0
    for cf in chunk_files:
        payload_path = cf.with_name(
            cf.name.removesuffix(".global-transcript.txt") + ".payload.json"
        )
        if not payload_path.exists():
            failed_chunk_count += 1
        chunk_txt = cf.read_text(encoding="utf-8").strip() if cf.exists() else ""
        if len(chunk_txt) < SILENT_CHARS_LIMIT:
            silent_chunk_count += 1

    # Gap analysis: intervals significantly larger than typical → gap
    gap_min_ivl = typical_ivl_s + GAP_THRESHOLD_S
    gaps: list[dict] = []
    for i in range(len(starts) - 1):
        ivl = starts[i + 1] - starts[i]
        if ivl > gap_min_ivl:
            gaps.append({
                "start_s":    starts[i] + typical_ivl_s,
                "end_s":      starts[i + 1],
                "duration_s": ivl - typical_ivl_s,
            })
    gap_count   = len(gaps)
    gap_seconds = sum(g["duration_s"] for g in gaps)

    # Last timestamp in transcript — handles both [HH:MM:SS] and [HH:MM:SS - HH:MM:SS]
    # Captures the END time of each bracketed range so we get the true coverage end.
    ts_matches = re.findall(
        r'\[(?:\d{2}:\d{2}:\d{2}\s*-\s*)?(\d{2}):(\d{2}):(\d{2})\]', transcript
    )
    transcript_end_s = max(
        (int(h) * 3600 + int(m) * 60 + int(s) for h, m, s in ts_matches),
        default=0,
    )

    # Tail coverage flag — computed before source_status so both can use it
    tail_coverage_low = (
        timeline_end_s > 0
        and transcript_end_s < timeline_end_s * TAIL_COVERAGE_RATIO
    )

    # Source status
    source_status = "partial" if (
        failed_chunk_count > 0 or gap_seconds > 60 or tail_coverage_low
    ) else "full"

    # Warnings
    warnings: list[str] = []
    if tail_coverage_low:
        threshold = int(timeline_end_s * TAIL_COVERAGE_RATIO)
        warnings.append(
            f"tail_coverage_low: transcript ends at {transcript_end_s}s,"
            f" expected ≥{threshold}s (estimated stream end: {timeline_end_s}s)"
        )
    if gaps:
        gap_detail = ", ".join(
            f"{fmt_ts(g['start_s'])}–{fmt_ts(g['end_s'])} ({g['duration_s']}s)"
            for g in gaps
        )
        warnings.append(f"gaps_detected: {gap_detail}")
    if failed_chunk_count:
        warnings.append(
            f"payload_missing: {failed_chunk_count}/{len(chunk_files)} chunk payload files missing;"
            " visual frames may be unavailable for multimodal synthesis"
        )
    if chunk_files and not all_frames:
        warnings.append(
            "visual_evidence_missing: no keyframe payloads were loaded;"
            " this run is transcript-only and is not a fair multimodal A/B test"
        )

    return {
        "base":                base,
        "run_ts":              selected_ts,
        "source_type":         "live",
        "source_status":       source_status,
        "chunk_count":         len(chunk_files),
        "transcript_chars":    len(transcript.strip()),
        "frame_count":         len(all_frames),
        "first_timestamp_s":   first_timestamp_s,
        "last_timestamp_s":    transcript_end_s,
        "timeline_end_s":      timeline_end_s,
        "timeline_duration_s": timeline_duration_s,
        "gap_count":           gap_count,
        "gap_seconds":         int(gap_seconds),
        "gaps":                gaps,
        "silent_chunk_count":  silent_chunk_count,
        "failed_chunk_count":  failed_chunk_count,
        "synthesis_provider":  "gemini",
        "synthesis_model":     GEMINI_MODEL,
        "synthesis_pass":      "one-shot",
        "warnings":            warnings,
    }


def check_markdown_body_coverage(gemini_text: str, manifest: dict) -> dict:
    """Warn if the last timestamped chapter in the output ends too early.

    Parses '### [HH:MM:SS - HH:MM:SS]' headings; compares to timeline_end_s.
    Returns body_last_chapter_end_s, body_tail_gap_s, body_coverage_status
    so the caller can persist these fields to the QC JSON.
    """
    heading_ends = re.findall(
        r'###\s+\[\d{2}:\d{2}:\d{2}\s*-\s*(\d{2}):(\d{2}):(\d{2})\]',
        gemini_text,
    )
    if not heading_ends:
        print("[warn] body_coverage: no '### [HH:MM:SS - HH:MM:SS]' headings found")
        return {"body_last_chapter_end_s": 0, "body_tail_gap_s": 0, "body_coverage_status": "no_headings"}

    lh, lm, ls = heading_ends[-1]
    body_end_s     = int(lh) * 3600 + int(lm) * 60 + int(ls)
    timeline_end_s = manifest.get("timeline_end_s", 0)

    if timeline_end_s > 0:
        gap_s = timeline_end_s - body_end_s
        if gap_s > BODY_COVERAGE_GAP_S:
            print(
                f"[warn] body_coverage: last chapter ends {fmt_ts(body_end_s)},"
                f" stream ends {fmt_ts(timeline_end_s)} — gap {gap_s}s"
                f" (threshold {BODY_COVERAGE_GAP_S}s): tail may be truncated"
            )
            return {"body_last_chapter_end_s": body_end_s, "body_tail_gap_s": gap_s, "body_coverage_status": "warning"}
        else:
            print(
                f"[ok]  body_coverage: last chapter {fmt_ts(body_end_s)},"
                f" stream end {fmt_ts(timeline_end_s)}, gap {gap_s}s"
            )
            return {"body_last_chapter_end_s": body_end_s, "body_tail_gap_s": gap_s, "body_coverage_status": "ok"}
    else:
        print(f"[ok]  body_coverage: last chapter {fmt_ts(body_end_s)}"
              f" (no stream timeline reference)")
        return {"body_last_chapter_end_s": body_end_s, "body_tail_gap_s": 0, "body_coverage_status": "ok"}


def prepend_quality_header(gemini_text: str, manifest: dict) -> str:
    """Inject a deterministic QC blockquote at the top of the final Markdown.

    Called after Gemini returns, before file write. Does not touch Gemini body.
    """
    def s_to_hms(s: int) -> str:
        h, r = divmod(s, 3600)
        m, sec = divmod(r, 60)
        return f"{h:02d}:{m:02d}:{sec:02d}"

    status  = manifest["source_status"]
    provider = manifest.get("synthesis_provider", "gemini")
    lines   = [
        "> **Live Final QC**",
        f"> - 输入类型: live | provider: {provider} | 合成模型: {manifest['synthesis_model']}"
        f" | synthesis_pass: {manifest['synthesis_pass']}",
        f"> - 采集状态: {status}",
        f"> - 覆盖时间: {s_to_hms(manifest['first_timestamp_s'])}"
        f" – {s_to_hms(manifest['timeline_end_s'])}",
        f"> - chunks: {manifest['chunk_count']}"
        f" | gaps: {manifest['gap_count']}"
        f" | transcript: {manifest['transcript_chars']:,} 字"
        f" | frames: {manifest['frame_count']}",
        f"> - 确定性附录: 完整逐字稿"
        f" ({manifest.get('transcript_appendix_chars', 0):,} 字)"
        f" | 视觉证据索引 ({manifest.get('visual_evidence_count', 0)} 帧)",
    ]

    if status in ("partial", "interrupted"):
        lines.append(
            f"> - ⚠️ 采集状态: {status}"
            " — 当前文档仅覆盖已采集片段，不代表完整直播内容。"
        )

    for w in manifest.get("warnings", []):
        if w.startswith("gaps_detected:"):
            lines.append(f"> - 已知缺口: {w[len('gaps_detected:'):].strip()}")
        elif w.startswith("tail_coverage_low:"):
            lines.append(f"> - ⚠️ 尾部覆盖不足: {w[len('tail_coverage_low:'):].strip()}")
        elif w.startswith("body_tail_coverage_low:"):
            lines.append(f"> - ⚠️ 正文尾段截断: {w[len('body_tail_coverage_low:'):].strip()}")
        elif w.startswith("body_coverage_unverifiable:"):
            lines.append(f"> - ⚠️ 正文覆盖无法验证: {w[len('body_coverage_unverifiable:'):].strip()}")
        elif w.startswith("payload_missing:"):
            lines.append(f"> - ⚠️ Payload 缺失: {w[len('payload_missing:'):].strip()}")
        elif w.startswith("visual_evidence_missing:"):
            lines.append(f"> - ⚠️ 视觉证据缺失: {w[len('visual_evidence_missing:'):].strip()}")

    return "\n".join(lines) + "\n\n" + gemini_text


def _md_cell(text: str) -> str:
    return str(text).replace("\n", " ").replace("|", "\\|").strip()


def build_visual_evidence_index(frames: list[dict]) -> str:
    """Build a deterministic, searchable index of frames sent to Gemini."""
    lines = [
        "## 附录 B：视觉证据索引",
        "",
        f"共 {len(frames)} 帧。该索引由本地 payload 确定性生成，不额外消耗模型 API。",
        "",
        "| 时间 | 标记 | 文件 |",
        "|------|------|------|",
    ]
    for frame in frames:
        ts = fmt_ts(int(frame.get("timestamp_s", 0)))
        marker = frame.get("marker") or f"Frame [{ts}]"
        path = frame.get("path", "")
        lines.append(f"| {ts} | {_md_cell(marker)} | `{_md_cell(path)}` |")
    return "\n".join(lines)


def append_deterministic_appendices(gemini_text: str, transcript: str, frames: list[dict]) -> str:
    """Append auditable local artifacts after Gemini body without extra API calls."""
    transcript = transcript.rstrip()
    sections = [
        gemini_text.rstrip(),
        "---",
        "## 附录 A：完整逐字稿",
        "",
        "以下为本地转写得到的完整文字记录，保留时间戳，便于检索、复盘和重新生成摘要。",
        "",
        "````text",
        transcript,
        "````",
        "",
        build_visual_evidence_index(frames),
        "",
    ]
    return "\n".join(sections)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--base",           required=True,       help="Stream base name")
    ap.add_argument("--runs-dir",       default="runs",      help="Dir with chunk files")
    ap.add_argument("--markdowns-dir",  default="Markdowns", help="Output dir")
    ap.add_argument("--run-ts",         default=None,
                    help="Specific run timestamp YYYYMMDD-HHMMSS (default: latest)")
    ap.add_argument("--provider", choices=("gemini", "qwen"), default="gemini",
                    help="Synthesis provider (default: gemini)")
    ap.add_argument("--output-label", default="",
                    help="Optional suffix for A/B outputs, e.g. gemini35 or qwen")
    ap.add_argument("--qwen-max-frames", type=int, default=QWEN_DEFAULT_MAX_FRAMES,
                    help=f"Qwen image cap, 1-{QWEN_IMAGE_HARD_LIMIT} (default: {QWEN_DEFAULT_MAX_FRAMES})")
    ap.add_argument("--max-frames", type=int, default=0,
                    help="Provider-neutral image cap for fair A/B tests; 0 keeps provider default")
    ap.add_argument("--qwen-thinking", action="store_true",
                    help="Enable Qwen thinking mode; off by default to control token cost")
    ap.add_argument("--thinking-budget", type=int, default=4096,
                    help="Thinking token budget for providers that support it")
    ap.add_argument("--max-retries", type=int, default=MAX_RETRIES,
                    help=f"Provider retry cap (default: {MAX_RETRIES})")
    ap.add_argument("--max-continuations", type=int, default=MAX_CONTINUATIONS,
                    help=f"Provider continuation cap after truncation (default: {MAX_CONTINUATIONS})")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print input/QC/provider budget only; do not call provider or write Markdown")
    ap.add_argument("--mock-gemini-text", default="",
                    help="Offline validation only: use this file as provider output and do not call provider")
    args = ap.parse_args()

    provider = args.provider
    output_label = args.output_label.strip()
    if provider == "qwen" and not output_label:
        output_label = "qwen"
    qwen_max_frames = max(1, min(args.qwen_max_frames, QWEN_IMAGE_HARD_LIMIT))

    if provider == "gemini":
        api_key = (
            os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENCLAW_GOOGLE_API_KEY") or ""
        ).strip()
        provider_model = GEMINI_MODEL
    else:
        api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
        provider_model = QWEN_MODEL
    if not api_key and not args.dry_run and not args.mock_gemini_text:
        env_name = "DASHSCOPE_API_KEY" if provider == "qwen" else "GEMINI_API_KEY"
        print(f"[!] No {env_name} — set the env var and re-run.")
        sys.exit(1)

    runs_dir      = Path(args.runs_dir)
    markdowns_dir = Path(args.markdowns_dir)
    pattern       = f"stream-{args.base}_chunk*.global-transcript.txt"
    all_found     = list(runs_dir.glob(pattern))

    if not all_found:
        print(f"ERROR: no files matching {runs_dir / pattern}", file=sys.stderr)
        sys.exit(1)

    if args.run_ts:
        chunk_files = sorted(
            [f for f in all_found if extract_run_ts(f) == args.run_ts],
            key=parse_chunk_start,
        )
        if not chunk_files:
            all_ts = sorted({extract_run_ts(f) for f in all_found})
            print(f"ERROR: run-ts '{args.run_ts}' not found. Available: {all_ts}",
                  file=sys.stderr)
            sys.exit(1)
        selected_ts = args.run_ts
    else:
        chunk_files = sorted(all_found, key=parse_chunk_start)
        selected_ts = extract_run_ts(sorted(chunk_files, key=parse_chunk_start)[-1])

    print(f"Chunks   : {len(chunk_files)} (run: {selected_ts})")

    transcript = build_combined_transcript(chunk_files)
    all_frames = collect_all_frames(chunk_files)

    if not transcript.strip():
        print("ERROR: no transcript content — check chunk files", file=sys.stderr)
        sys.exit(1)

    print(f"Transcript: {len(transcript):,} chars")
    print(f"Frames    : {len(all_frames)} total")

    manifest = live_final_qc(chunk_files, transcript, all_frames, args.base, selected_ts)
    manifest["synthesis_provider"] = provider
    manifest["synthesis_model"] = provider_model
    if provider == "qwen":
        manifest["qwen_thinking_enabled"] = bool(args.qwen_thinking)
    label_part = f".{output_label}" if output_label else ""
    qc_path  = runs_dir / f"stream-{args.base}-{selected_ts}{label_part}.final-qc.json"
    qc_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"QC manifest : {qc_path}  [{manifest['source_status']}]")
    for w in manifest["warnings"]:
        print(f"  [warn] {w}")

    max_successful_calls = 1 + max(0, args.max_continuations)
    provider_image_limit = GEMINI_IMAGE_HARD_LIMIT if provider == "gemini" else qwen_max_frames
    if args.max_frames > 0:
        image_limit = max(1, min(args.max_frames, provider_image_limit))
    else:
        image_limit = provider_image_limit
    print(f"\n=== {provider} budget ===")
    print(f"  model                : {provider_model}")
    print("  synthesis_pass       : one-shot")
    print(f"  max successful calls : {max_successful_calls} (1 initial + {args.max_continuations} continuation)")
    print(f"  retry cap            : {args.max_retries}")
    print(f"  image cap            : {image_limit}")
    if args.max_frames > 0:
        print(f"  fair A/B max frames  : {args.max_frames}")
    print("  duplicate synthesis  : false")
    if output_label:
        print(f"  output label         : {output_label}")
    if args.mock_gemini_text:
        print(f"  offline validation   : {args.mock_gemini_text} (no API call)")

    if args.dry_run:
        dry_parts, dry_policy = build_gemini_parts(
            transcript,
            all_frames,
            provider=provider,
            image_limit=image_limit,
        )
        manifest["frame_policy"] = dry_policy
        manifest["provider_parts_count"] = len(dry_parts)
        qc_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[dry-run] Skipping {provider} call and Markdown write.")
        return

    if args.mock_gemini_text:
        print("\n=== Offline validation: using mock provider text ===")
        gemini_text = Path(args.mock_gemini_text).read_text(encoding="utf-8")
        manifest["synthesis_pass"] = "mock-one-shot"
        manifest["frame_policy"] = {
            "provider": provider,
            "total_frames": len(all_frames),
            "selected_frames": 0,
            "dropped_frames": len(all_frames),
            "cap": image_limit,
        }
    else:
        print(f"\n=== {provider}: Building NotebookLM document ===")
        parts, frame_policy = build_gemini_parts(
            transcript,
            all_frames,
            provider=provider,
            image_limit=image_limit,
        )
        manifest["frame_policy"] = frame_policy
        manifest["provider_parts_count"] = len(parts)

        if provider == "gemini":
            if not _GENAI_AVAILABLE:
                print("[!] google-genai not installed — run: pip install google-genai", file=sys.stderr)
                sys.exit(1)
            http_opts = types.HttpOptions(timeout=3600000)
            client    = genai.Client(api_key=api_key, http_options=http_opts)
            gemini_text = call_gemini(
                client, parts, args.base,
                model=provider_model,
                thinking_budget=args.thinking_budget,
                max_retries=args.max_retries,
                max_continuations=args.max_continuations,
            )
            manifest["provider_usage"] = {
                "provider": "gemini",
                "model": provider_model,
                "api_calls": None,
                "usage": {},
            }
        else:
            try:
                from openai import OpenAI
            except ImportError:
                print("[!] openai not installed — run: pip install openai", file=sys.stderr)
                sys.exit(1)
            client = OpenAI(
                api_key=api_key,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            )
            qwen_result = call_qwen(
                client, parts, args.base,
                model=provider_model,
                enable_thinking=args.qwen_thinking,
                thinking_budget=args.thinking_budget,
                max_retries=args.max_retries,
                max_continuations=args.max_continuations,
            )
            gemini_text = qwen_result.get("text")
            manifest["provider_usage"] = {k: v for k, v in qwen_result.items() if k != "text"}

    if not gemini_text:
        print(f"[!] {provider} synthesis failed — merged raw transcript still available.",
              file=sys.stderr)
        sys.exit(1)

    # Check body coverage before building the header so the warning appears in the QC block.
    coverage = check_markdown_body_coverage(gemini_text, manifest)
    manifest.update(coverage)
    if coverage["body_coverage_status"] == "warning":
        manifest["warnings"].append(
            f"body_tail_coverage_low: last chapter {fmt_ts(coverage['body_last_chapter_end_s'])},"
            f" gap {coverage['body_tail_gap_s']}s"
        )
    elif coverage["body_coverage_status"] == "no_headings":
        manifest["warnings"].append(
            "body_coverage_unverifiable: no timestamped chapter headings found in Gemini output"
        )
    manifest["transcript_appendix_chars"] = len(transcript.strip())
    manifest["visual_evidence_count"] = len(all_frames)
    manifest["deterministic_appendices"] = ["full_transcript", "visual_evidence_index"]
    # Re-write QC JSON with body coverage fields included.
    qc_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    gemini_text = prepend_quality_header(gemini_text, manifest)
    gemini_text = append_deterministic_appendices(gemini_text, transcript, all_frames)

    markdowns_dir.mkdir(parents=True, exist_ok=True)
    out_path = markdowns_dir / f"TTS_stream-{args.base}{('-' + output_label) if output_label else ''}.md"
    out_path.write_text(gemini_text, encoding="utf-8")
    print(f"\nNotebookLM document : {out_path}")
    print(f"  Size              : {len(gemini_text):,} chars")


if __name__ == "__main__":
    main()
