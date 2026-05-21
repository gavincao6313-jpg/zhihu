"""Build final structured Markdown from replay transcript.

Uses accurate per-segment timestamps from transcript.json (requires merge_vad=False run).
For each segment, sub-sentences get proportional offsets within the VAD window
(accurate to ≤ one segment duration ~2-5 seconds).

After building the raw transcript markdown, optionally calls Gemini 2.5 Flash to
produce a NotebookLM-ready knowledge document (same quality as zhihuTTS.py).

Requires:
    GEMINI_API_KEY or OPENCLAW_GOOGLE_API_KEY env var for Gemini synthesis.

Usage (Windows, from project root):
    set GEMINI_API_KEY=your_key
    python build_final_markdown.py
"""
import json
import os
import re
import time
from pathlib import Path

from google import genai
from google.genai import types

from utils import call_gemini, fmt_ts, parse_retry_delay

# ── Paths ───────────────────────────────────────────────────────────────────

RUNS_DIR        = Path(r"D:\zhihu\zhihu_url\runs")
MARKDOWNS_DIR   = Path(r"D:\zhihu\zhihu_url\Markdowns")
TRANSCRIPT_JSON = RUNS_DIR / "replay-20260518.transcript.json"
PAYLOAD_JSON    = RUNS_DIR / "replay-20260518.payload.json"
OUT_PATH        = RUNS_DIR / "replay-20260518-final.md"        # raw transcript markdown
NOTEBOOKLM_PATH = MARKDOWNS_DIR / "TTS_replay-20260518.md"    # Gemini knowledge doc

# ── Gemini config ────────────────────────────────────────────────────────────

GEMINI_MODEL            = "gemini-2.5-flash"
GEMINI_IMAGE_HARD_LIMIT = 3000   # Gemini 2.5 Flash API hard ceiling; ~50hr+ streams only
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
由于视频长达 2-3 小时，信息量极大。请保持极高的专注度，不要省略中间章节。如果你的输出达到了字数上限，请停在当前完整的段落，我会回复"继续"，你再接着上文输出。
"""


# ── Helpers ──────────────────────────────────────────────────────────────────

def split_sentences(text: str) -> list[str]:
    parts = re.split(r'(?<=[。！？；])', text)
    return [s.strip() for s in parts if s.strip()]


def segments_to_text(segs: list[dict]) -> str:
    """Format transcript segments as [HH:MM:SS - HH:MM:SS] text lines."""
    lines = []
    for seg in segs:
        if not str(seg.get("text", "")).strip():
            continue
        ts = f"[{fmt_ts(float(seg['start']))} - {fmt_ts(float(seg['end']))}]"
        lines.append(f"{ts} {seg['text'].strip()}")
    return "\n".join(lines)


def build_replay_gemini_parts(payload: dict, transcript_text: str) -> list:
    """Build Gemini input parts: prompt + transcript text + all keyframes.

    All kept frames are sent to maximise Gemini's multimodal understanding.
    Priority ordering (slide > annotation > context) only kicks in when the
    total exceeds GEMINI_IMAGE_HARD_LIMIT (3000), which requires ~50+ hours
    of stream content at current extraction thresholds.
    """
    frames = payload.get("frames", [])
    total  = len(frames)

    if total <= GEMINI_IMAGE_HARD_LIMIT:
        selected = sorted(frames, key=lambda f: f.get("timestamp_s", 0))
    else:
        # Extremely long stream: priority-sample down to the hard limit.
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

    slide_count = sum(1 for f in selected if "type=slide"      in f.get("marker", ""))
    annot_count = sum(1 for f in selected if "type=annotation" in f.get("marker", ""))

    parts: list = [GEMINI_PROMPT_TEXT, transcript_text]
    loaded = 0
    for frame in selected:
        frame_path = Path(frame["path"])
        if not frame_path.exists():
            continue
        parts.append(frame.get("marker", f"Frame [{fmt_ts(frame.get('timestamp_s', 0))}]"))
        parts.append(types.Part(
            inline_data=types.Blob(mime_type="image/jpeg", data=frame_path.read_bytes())
        ))
        loaded += 1

    print(f"  Gemini parts: transcript {len(transcript_text):,} chars, "
          f"{loaded}/{total} frames (slide={slide_count}, annot={annot_count})",
          flush=True)
    return parts


# ── Load data ────────────────────────────────────────────────────────────────

with open(TRANSCRIPT_JSON, encoding="utf-8") as f:
    transcript = json.load(f)

with open(PAYLOAD_JSON, encoding="utf-8") as f:
    payload = json.load(f)

segments = transcript["segments"]
events   = payload.get("events", [])

if not segments:
    raise SystemExit(
        "transcript.json has no segments — re-run transcribe_replay.py with SENSEVOICE_MERGE_VAD=false"
    )

total_duration   = segments[-1]["end"]
annotation_count = sum(1 for e in events if e.get("type") == "annotation")
slide_times      = sorted(e["frame_idx"] for e in events if e.get("type") == "slide")

# ── Expand segments → (timestamp_s, sentence) pairs ──────────────────────────

stamped: list[tuple[float, str]] = []
for seg in segments:
    seg_start = float(seg["start"])
    seg_end   = float(seg["end"])
    seg_dur   = max(seg_end - seg_start, 0.01)
    subs      = split_sentences(seg["text"])
    if not subs:
        continue
    seg_chars = sum(len(s) for s in subs)
    char_pos  = 0
    for s in subs:
        frac = char_pos / seg_chars if seg_chars > 0 else 0.0
        stamped.append((seg_start + frac * seg_dur, s))
        char_pos += len(s)

total_chars     = sum(len(s) for _, s in stamped)
total_sentences = len(stamped)

# ── Build raw transcript markdown ────────────────────────────────────────────

lines: list[str] = []
lines += [
    "# 知乎直播回放 — 完整转写文档",
    "",
    "| 属性 | 值 |",
    "|---|---|",
    f"| 日期 | 2026-05-18 |",
    f"| 时长 | {fmt_ts(int(total_duration))} |",
    f"| 总字符数 | {total_chars:,} |",
    f"| 句子数 | {total_sentences:,} |",
    f"| VAD分段数 | {len(segments):,} |",
    f"| 幻灯片切换 | {len(slide_times)} 次 |",
    f"| 转写引擎 | SenseVoiceSmall (FunASR) + FSMN-VAD |",
    f"| 转写方式 | 回放视频离线转写 (VAD分段精确时间戳) |",
    f"| 关键帧提取 | {payload.get('frames_count', 0)} 张 |",
    "",
    "---",
    "",
]

slide_idx   = 0
section_num = 1
lines += [f"## 第 {section_num} 部分 — {fmt_ts(0)}", ""]

buf: list[str] = []
for ts, sent in stamped:
    while slide_idx < len(slide_times) and ts >= slide_times[slide_idx]:
        lines.extend(buf)
        buf = []
        section_num += 1
        slide_ts = slide_times[slide_idx]
        lines += ["", "---", "", f"## 第 {section_num} 部分 — {fmt_ts(slide_ts)}", ""]
        slide_idx += 1
    buf.append(f"> [{fmt_ts(ts)}] {sent}")

lines.extend(buf)

lines += [
    "",
    "---",
    "",
    "## 转写统计信息",
    "",
    "| 指标 | 值 |",
    "|---|---|",
    f"| 总字符数 | {total_chars:,} |",
    f"| 句子数 | {total_sentences:,} |",
    f"| VAD分段数 | {len(segments):,} |",
    f"| 幻灯片切换 | {len(slide_times)} |",
    f"| 标注/画笔事件 | {annotation_count} |",
    f"| 关键帧提取 | {payload.get('frames_count', 0)} |",
    f"| 音频时长 | {fmt_ts(int(total_duration))} |",
    f"| 时间戳方式 | VAD分段精确时间戳 (误差 ≤ 单段时长 ~2-5s) |",
    "",
]

OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
print(f"Raw transcript: {OUT_PATH}")
print(f"Sections: {section_num}  Sentences: {total_sentences}  VAD segments: {len(segments)}")

# ── Gemini synthesis → NotebookLM document ───────────────────────────────────

api_key = (
    os.environ.get("GEMINI_API_KEY")
    or os.environ.get("OPENCLAW_GOOGLE_API_KEY")
    or ""
).strip()

if not api_key:
    print("\n[!] No GEMINI_API_KEY — skipping Gemini synthesis.")
    print("    Set GEMINI_API_KEY and re-run to produce the NotebookLM document.")
else:
    print("\n=== Gemini: Building NotebookLM knowledge document ===")
    MARKDOWNS_DIR.mkdir(parents=True, exist_ok=True)

    transcript_text = segments_to_text(segments)
    parts = build_replay_gemini_parts(payload, transcript_text)  # all frames, no cap

    http_opts = types.HttpOptions(timeout=3600000)
    client = genai.Client(api_key=api_key, http_options=http_opts)

    gemini_text = call_gemini(client, parts, "replay-20260518")
    if gemini_text:
        NOTEBOOKLM_PATH.write_text(gemini_text, encoding="utf-8")
        print(f"\nNotebookLM document: {NOTEBOOKLM_PATH}")
        print(f"  Size: {len(gemini_text):,} chars")
    else:
        print("[!] Gemini synthesis failed — raw transcript still available at:")
        print(f"    {OUT_PATH}")
