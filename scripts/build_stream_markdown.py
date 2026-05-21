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

    groups: dict[str, list[Path]] = defaultdict(list)
    for f in all_found:
        groups[extract_run_ts(f)].append(f)

    selected_ts = args.run_ts if args.run_ts else max(groups.keys())
    if selected_ts not in groups:
        print(f"ERROR: run-ts '{selected_ts}' not found. Available: {sorted(groups)}",
              file=sys.stderr)
        sys.exit(1)

    if len(groups) > 1:
        print(f"[warn] {len(groups)} runs for '{args.base}' — using: {selected_ts}")

    chunk_files = sorted(groups[selected_ts], key=parse_chunk_start)
    print(f"Chunks   : {len(chunk_files)} (run: {selected_ts})")

    transcript = build_combined_transcript(chunk_files)
    all_frames = collect_all_frames(chunk_files)

    if not transcript.strip():
        print("ERROR: no transcript content — check chunk files", file=sys.stderr)
        sys.exit(1)

    print(f"Transcript: {len(transcript):,} chars")
    print(f"Frames    : {len(all_frames)} total")

    print("\n=== Gemini: Building NotebookLM document ===")
    parts = build_gemini_parts(transcript, all_frames)

    http_opts = types.HttpOptions(timeout=3600000)
    client    = genai.Client(api_key=api_key, http_options=http_opts)

    gemini_text = call_gemini(client, parts, args.base)
    if not gemini_text:
        print("[!] Gemini synthesis failed — merged raw transcript still available.",
              file=sys.stderr)
        sys.exit(1)

    markdowns_dir.mkdir(parents=True, exist_ok=True)
    out_path = markdowns_dir / f"TTS_stream-{args.base}.md"
    out_path.write_text(gemini_text, encoding="utf-8")
    print(f"\nNotebookLM document : {out_path}")
    print(f"  Size              : {len(gemini_text):,} chars")


if __name__ == "__main__":
    main()
