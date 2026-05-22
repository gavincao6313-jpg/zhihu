"""Post-stream Gemini synthesis: assemble all live chunks → NotebookLM document.

Run after zhihuTTS_stream.py finishes and merge_stream_chunks.py has produced
the raw merged transcript. This script:
  1. Loads all per-chunk global-transcript.txt → combined full transcript
  2. Loads all per-chunk payload.json → all keyframe images, globally sorted
  3. Calls Gemini 2.5 Flash with the full prompt + all frames (no cap)
  4. Writes a NotebookLM-ready document to Markdowns/TTS_stream-<base>.md

Requires GEMINI_API_KEY or OPENCLAW_GOOGLE_API_KEY env var.

Usage (Windows):
    set GEMINI_API_KEY=your_key
    python scripts\\build_stream_markdown.py --base zhihu-gaowei-20260518

Usage (Mac/Linux):
    GEMINI_API_KEY=your_key python scripts/build_stream_markdown.py --base zhihu-gaowei-20260518

Options:
    --base          Stream base name (required). Matches stream-{base}_chunk* files.
    --runs-dir      Directory with per-chunk files (default: runs)
    --markdowns-dir Output directory for NotebookLM document (default: Markdowns)
    --run-ts        Use a specific run timestamp YYYYMMDD-HHMMSS (default: latest run)
"""
import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

from google import genai
from google.genai import types

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils import call_gemini, extract_run_ts, fmt_ts

# ── Gemini config ─────────────────────────────────────────────────────────────

GEMINI_MODEL            = "gemini-2.5-flash"
GEMINI_IMAGE_HARD_LIMIT = 3000   # API ceiling; fallback priority sampling above this
MAX_RETRIES             = 6
MAX_CONTINUATIONS       = 20
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


# ── Gemini input assembly ─────────────────────────────────────────────────────

def select_frames(frames: list[dict]) -> list[dict]:
    """Return all frames; apply priority sampling only when > GEMINI_IMAGE_HARD_LIMIT."""
    if len(frames) <= GEMINI_IMAGE_HARD_LIMIT:
        return frames

    slide_frames = [f for f in frames if "type=slide"      in f.get("marker", "")]
    annot_frames = [f for f in frames if "type=annotation" in f.get("marker", "")]
    ctx_frames   = [f for f in frames
                    if "type=slide"      not in f.get("marker", "")
                    and "type=annotation" not in f.get("marker", "")]

    cap      = GEMINI_IMAGE_HARD_LIMIT
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


def build_gemini_parts(transcript: str, frames: list[dict]) -> list:
    selected    = select_frames(frames)
    slide_count = sum(1 for f in selected if "type=slide"      in f.get("marker", ""))
    annot_count = sum(1 for f in selected if "type=annotation" in f.get("marker", ""))

    parts: list = [GEMINI_PROMPT_TEXT, transcript]
    loaded = 0
    for frame in selected:
        fp = Path(frame["path"])
        if not fp.exists():
            continue
        parts.append(frame.get("marker", f"Frame [{fmt_ts(frame.get('timestamp_s', 0))}]"))
        parts.append(types.Part(
            inline_data=types.Blob(mime_type="image/jpeg", data=fp.read_bytes())
        ))
        loaded += 1

    print(f"  Gemini parts: transcript {len(transcript):,} chars, "
          f"{loaded}/{len(frames)} frames (slide={slide_count}, annot={annot_count})",
          flush=True)
    return parts


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
        "synthesis_model":     GEMINI_MODEL,
        "synthesis_pass":      "one-shot",
        "warnings":            warnings,
    }


def check_markdown_body_coverage(gemini_text: str, manifest: dict) -> None:
    """Warn if the last timestamped chapter in the output ends too early.

    Parses '### [HH:MM:SS - HH:MM:SS]' headings; compares to timeline_end_s.
    This catches the one-shot attention-compression problem where Gemini stops
    summarising the last N minutes even though the source transcript is complete.
    """
    heading_ends = re.findall(
        r'###\s+\[\d{2}:\d{2}:\d{2}\s*-\s*(\d{2}):(\d{2}):(\d{2})\]',
        gemini_text,
    )
    if not heading_ends:
        print("[warn] body_coverage: no '### [HH:MM:SS - HH:MM:SS]' headings found")
        return

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
        else:
            print(
                f"[ok]  body_coverage: last chapter {fmt_ts(body_end_s)},"
                f" stream end {fmt_ts(timeline_end_s)}, gap {gap_s}s"
            )
    else:
        print(f"[ok]  body_coverage: last chapter {fmt_ts(body_end_s)}"
              f" (no stream timeline reference)")


def prepend_quality_header(gemini_text: str, manifest: dict) -> str:
    """Inject a deterministic QC blockquote at the top of the final Markdown.

    Called after Gemini returns, before file write. Does not touch Gemini body.
    """
    def s_to_hms(s: int) -> str:
        h, r = divmod(s, 3600)
        m, sec = divmod(r, 60)
        return f"{h:02d}:{m:02d}:{sec:02d}"

    status  = manifest["source_status"]
    lines   = [
        "> **Live Final QC**",
        f"> - 输入类型: live | 合成模型: {manifest['synthesis_model']}"
        f" | synthesis_pass: {manifest['synthesis_pass']}",
        f"> - 采集状态: {status}",
        f"> - 覆盖时间: {s_to_hms(manifest['first_timestamp_s'])}"
        f" – {s_to_hms(manifest['timeline_end_s'])}",
        f"> - chunks: {manifest['chunk_count']}"
        f" | gaps: {manifest['gap_count']}"
        f" | transcript: {manifest['transcript_chars']:,} 字"
        f" | frames: {manifest['frame_count']}",
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

    return "\n".join(lines) + "\n\n" + gemini_text


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
    args = ap.parse_args()

    api_key = (
        os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENCLAW_GOOGLE_API_KEY") or ""
    ).strip()
    if not api_key:
        print("[!] No GEMINI_API_KEY — set the env var and re-run.")
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
    qc_path  = runs_dir / f"stream-{args.base}-{selected_ts}.final-qc.json"
    qc_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"QC manifest : {qc_path}  [{manifest['source_status']}]")
    for w in manifest["warnings"]:
        print(f"  [warn] {w}")

    print("\n=== Gemini: Building NotebookLM document ===")
    http_opts = types.HttpOptions(timeout=3600000)
    client    = genai.Client(api_key=api_key, http_options=http_opts)

    parts = build_gemini_parts(transcript, all_frames)
    gemini_text = call_gemini(client, parts, args.base)

    if not gemini_text:
        print("[!] Gemini synthesis failed — merged raw transcript still available.",
              file=sys.stderr)
        sys.exit(1)

    gemini_text = prepend_quality_header(gemini_text, manifest)

    markdowns_dir.mkdir(parents=True, exist_ok=True)
    out_path = markdowns_dir / f"TTS_stream-{args.base}.md"
    out_path.write_text(gemini_text, encoding="utf-8")
    print(f"\nNotebookLM document : {out_path}")
    print(f"  Size              : {len(gemini_text):,} chars")
    check_markdown_body_coverage(gemini_text, manifest)


if __name__ == "__main__":
    main()
