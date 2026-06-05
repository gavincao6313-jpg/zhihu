"""
A/B Test — Gemini synthesis for both branches, producing NotebookLM-ready documents.

Usage:
    cd D:\zhihu
    set GEMINI_API_KEY=xxx   (auto-falls back to OPENCLAW_GOOGLE_API_KEY)
    python gemini_synthesis_ab.py
"""
import json
import os
import re
import sys
import time
from pathlib import Path

# API key fallback
api_key = (
    os.environ.get("GEMINI_API_KEY")
    or os.environ.get("OPENCLAW_GOOGLE_API_KEY")
    or ""
).strip()
if not api_key:
    print("ERROR: Set GEMINI_API_KEY or OPENCLAW_GOOGLE_API_KEY", file=sys.stderr)
    sys.exit(1)

from google import genai
from google.genai import types

# ── Config ────────────────────────────────────────────────────────────────────
GEMINI_MODEL_CANDIDATES = [
    "gemini-3.5-flash",
]
GEMINI_IMAGE_HARD_LIMIT = 3000
# For A/B comparison, limit frames to slide + annotation only to reduce payload
# while still providing key visual information for Gemini
GEMINI_FRAME_LIMIT = 150  # slides (~79) + annotations (~71) ≈ 150
MAX_RETRIES = 4
MAX_CONTINUATIONS = 20
RETRY_DELAY = 30

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

# ── Helpers ────────────────────────────────────────────────────────────────────

def fmt_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def segments_to_text(segs: list[dict]) -> str:
    lines = []
    for seg in segs:
        if not str(seg.get("text", "")).strip():
            continue
        ts = f"[{fmt_ts(float(seg['start']))} - {fmt_ts(float(seg['end']))}]"
        lines.append(f"{ts} {seg['text'].strip()}")
    return "\n".join(lines)


def build_gemini_parts(payload: dict, transcript_text: str, frame_limit: int = GEMINI_FRAME_LIMIT) -> list:
    frames = payload.get("frames", [])
    total = len(frames)

    # Priority: slides first, then annotations, then context frames
    slide_frames = [f for f in frames if "type=slide" in f.get("marker", "")]
    annot_frames = [f for f in frames if "type=annotation" in f.get("marker", "")]
    ctx_frames = [f for f in frames
                  if "type=slide" not in f.get("marker", "")
                  and "type=annotation" not in f.get("marker", "")]

    # Try to fit within frame_limit, prioritizing slides > annotations > context
    cap = min(frame_limit, GEMINI_IMAGE_HARD_LIMIT)
    selected = list(slide_frames[:cap])
    remaining = cap - len(selected)
    if remaining > 0 and annot_frames:
        step = max(1, len(annot_frames) // remaining)
        selected += annot_frames[::step][:remaining]
        remaining = cap - len(selected)
    if remaining > 0 and ctx_frames:
        step = max(1, len(ctx_frames) // remaining)
        selected += ctx_frames[::step][:remaining]
    selected.sort(key=lambda f: f.get("timestamp_s", 0))

    slide_count = sum(1 for f in selected if "type=slide" in f.get("marker", ""))
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


def call_gemini_with_retry(client, parts: list, label: str, model: str = "gemini-2.5-flash") -> str | None:
    gemini_config = types.GenerateContentConfig(
        temperature=0.1,
        max_output_tokens=65536,
        thinking_config=types.ThinkingConfig(thinking_budget=4096),
    )

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"[{label}] Sending to Gemini ({len(parts)} parts)...", flush=True)
            chat = client.chats.create(model=model, config=gemini_config)
            response = chat.send_message(parts)
            full_text = response.text
            if not full_text:
                raise RuntimeError("Gemini returned empty response")

            candidate = response.candidates[0] if response.candidates else None
            for cont in range(MAX_CONTINUATIONS):
                if not candidate or candidate.finish_reason != types.FinishReason.MAX_TOKENS:
                    break
                print(f"[{label}] Output truncated, auto-continuing ({cont + 1})...", flush=True)
                response = chat.send_message("继续")
                chunk = response.text
                if not chunk:
                    break
                full_text += "\n" + chunk
                candidate = response.candidates[0] if response.candidates else None

            print(f"[{label}] Done: {len(full_text):,} chars", flush=True)
            return full_text

        except Exception as e:
            is_quota = "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)
            if is_quota:
                print(f"[{label}] Quota exhausted (429) — stopping retries to conserve quota", flush=True)
                return None
            delay = (int(float(re.search(r'retry in (\d+(?:\.\d+)?)s', str(e), re.IGNORECASE).group(1))) + 10
                     if re.search(r'retry in (\d+(?:\.\d+)?)s', str(e), re.IGNORECASE)
                     else RETRY_DELAY)
            print(f"[{label}] Error: {e} "
                  f"— retry in {delay}s (attempt {attempt}/{MAX_RETRIES})", flush=True)
            if attempt < MAX_RETRIES:
                time.sleep(delay)

    return None


# ── Process a single branch ────────────────────────────────────────────────────

def process_branch(transcript_json: Path, payload_json: Path, out_md: Path, label: str):
    print(f"\n{'=' * 60}")
    print(f"Processing: {label}")
    print(f"{'=' * 60}")

    with open(transcript_json, encoding="utf-8") as f:
        transcript = json.load(f)
    with open(payload_json, encoding="utf-8") as f:
        payload = json.load(f)

    segments = transcript["segments"]
    if not segments:
        print(f"[{label}] ERROR: no segments", file=sys.stderr)
        return None

    n_segs = len(segments)
    total_dur = segments[-1]["end"] - segments[0]["start"]
    backend = transcript.get("backend_used", "?")
    print(f"  Segments: {n_segs}  Duration: {total_dur:.0f}s  Backend: {backend}")

    transcript_text = segments_to_text(segments)
    parts = build_gemini_parts(payload, transcript_text)

    http_opts = types.HttpOptions(timeout=3600000)
    client = genai.Client(api_key=api_key, http_options=http_opts)

    # Try models in order
    for model in GEMINI_MODEL_CANDIDATES:
        print(f"  Trying model: {model} ...", flush=True)
        t0 = time.monotonic()
        gemini_text = call_gemini_with_retry(client, parts, label=f"{label}/{model}", model=model)
        elapsed = time.monotonic() - t0
        if gemini_text:
            out_md.parent.mkdir(parents=True, exist_ok=True)
            out_md.write_text(gemini_text, encoding="utf-8")
            print(f"[{label}] Model={model}  Size: {len(gemini_text):,} chars  Time: {elapsed:.0f}s")
            print(f"[{label}] Saved: {out_md}")
            return gemini_text
        else:
            print(f"[{label}] Model {model} failed after {elapsed:.0f}s, trying next...")

    print(f"[{label}] ALL models failed!")
    return None


# ── Main: process both branches ────────────────────────────────────────────────

FILE_TRANSCRIPT = Path(r"D:\zhihu\zhihu_file\runs\ab-file-english-practice.transcript.json")
FILE_PAYLOAD    = Path(r"D:\zhihu\zhihu_file\runs\ab-file-english-practice.payload.json")
FILE_OUT        = Path(r"D:\zhihu\zhihu_file\Markdowns\TTS_ab-file-english-practice.md")

URL_TRANSCRIPT  = Path(r"D:\zhihu\zhihu_url\runs\ab-url-english-practice.transcript.json")
URL_PAYLOAD     = Path(r"D:\zhihu\zhihu_url\runs\ab-url-english-practice.payload.json")
URL_OUT         = Path(r"D:\zhihu\zhihu_url\Markdowns\TTS_ab-url-english-practice.md")

print("=" * 60)
print("A/B Test — Gemini NotebookLM Synthesis")
print(f"Models: {', '.join(GEMINI_MODEL_CANDIDATES)}")
print(f"API key: {'set' if api_key else 'MISSING'}")
print("=" * 60)

t_start = time.monotonic()

# FILE branch already has gemini-3.5-flash output from earlier run — skip
print("[SKIP] FILE-branch — already done with gemini-3.5-flash (8,017 chars)")
print(f"        {FILE_OUT}")

url_result  = process_branch(URL_TRANSCRIPT, URL_PAYLOAD, URL_OUT, "URL-branch")

total_t = time.monotonic() - t_start
print(f"\n{'=' * 60}")
print(f"Done! ({total_t:.0f}s)")
print(f"  File output: {FILE_OUT} (8,017 chars, from earlier run)")
if url_result:
    print(f"  URL output : {URL_OUT} ({len(url_result):,} chars)")
else:
    print(f"  URL output : FAILED (quota exhausted, retry tomorrow)")
print(f"{'=' * 60}")
