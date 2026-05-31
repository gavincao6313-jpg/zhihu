"""Run dual-model verification (Gemini + Qwen) on a single video.

Preprocessing (keyframes + SenseVoice transcription) runs once.
Both models receive the same transcript + frames → produce independent
NotebookLM-ready Markdown documents for cross-validation.

Usage:
    cd d:\zhihu\zhihu_file
    .venv-sensevoice\Scripts\python.exe run_dual_model.py "实操带练：客服与标书工作流作业解析"
"""
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.chdir(str(Path(__file__).parent))

# Fix Windows GBK encoding — must happen before any print
sys.stdout.reconfigure(encoding="utf-8")

from zhihuTTS_video import (
    extract_keyframes,
    transcribe_audio_chunked,
    transcript_to_text,
    frame_marker,
    TRANSCRIBE_CHUNK_DURATION_S,
)
from zhihuTTS import (
    PROMPT_TEXT,
    MARKDOWNS_DIR,
    _save_preprocess_cache,
    _load_preprocess_cache,
    tprint,
    VIDEOS_DIR,
    TRANSCRIPT_APPENDIX_HEADING,
)
from utils import (
    call_gemini, call_qwen,
    extract_qwen_critical_facts, extract_qwen_narrative_blocks,
    ensure_qwen_critical_fact_appendix, ensure_qwen_narrative_appendix,
    check_qwen_notebooklm_quality,
)
from google import genai
from google.genai import types
from openai import OpenAI

# ── Config ──────────────────────────────────────────────
VIDEO_STEM = sys.argv[1] if len(sys.argv) > 1 else "实操带练：客服与标书工作流作业解析"
VIDEO_PATH = VIDEOS_DIR / f"{VIDEO_STEM}.mp4"

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")  # pro free-tier quota often exhausted
QWEN_MODEL = os.environ.get("QWEN_MODEL", "qwen3.6-plus")
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
QWEN_MAX_FRAMES = 250  # DashScope limits data-uri per request

DATE_PREFIX = date.today().strftime("%m%d")
GEMINI_OUTPUT = MARKDOWNS_DIR / f"TTS_{DATE_PREFIX}_{VIDEO_STEM}-gemini.md"
QWEN_OUTPUT = MARKDOWNS_DIR / f"TTS_{DATE_PREFIX}_{VIDEO_STEM}-qwen.md"
MANIFEST_OUTPUT = MARKDOWNS_DIR / f"TTS_{DATE_PREFIX}_{VIDEO_STEM}-manifest.json"

MARKDOWNS_DIR.mkdir(parents=True, exist_ok=True)


def _transcript_appendix(transcript_text: str) -> str:
    return (
        "\n\n---\n\n"
        f"{TRANSCRIPT_APPENDIX_HEADING}\n\n"
        "以下为本地转写得到的完整文字记录，保留时间戳，便于检索、复盘和重新生成摘要。\n\n"
        "```text\n"
        f"{transcript_text.rstrip()}\n"
        "```\n"
    )


def main():
    if not VIDEO_PATH.exists():
        print(f"视频文件不存在: {VIDEO_PATH}")
        sys.exit(1)

    print("=" * 60)
    print(f"  双模型验证: {VIDEO_STEM}")
    print(f"  Gemini 模型: {GEMINI_MODEL}")
    print(f"  Qwen 模型:   {QWEN_MODEL}")
    print(f"  视频大小:    {VIDEO_PATH.stat().st_size / 1024**2:.0f} MB")
    print("=" * 60)

    # ── Phase 1: Preprocessing (once) ─────────────────────
    print("\n" + "-" * 40)
    print("  Phase 1: 预处理（关键帧 + 语音转写）")
    print("-" * 40 + "\n")

    video_label = f"preprocess {VIDEO_STEM[:30]}"

    cached = _load_preprocess_cache(VIDEO_PATH, video_label)
    if cached:
        events, kept_frames, transcript = cached
        print(f"  ✓ 命中缓存: {len(kept_frames)} 帧, {len(transcript.get('segments', []))} 分段")
    else:
        tprint(f"[{video_label}] 提取关键帧 & 分片转录音频...")
        events, kept_frames = extract_keyframes(VIDEO_PATH)
        transcript = transcribe_audio_chunked(VIDEO_PATH, TRANSCRIBE_CHUNK_DURATION_S)
        _save_preprocess_cache(VIDEO_PATH, events, kept_frames, transcript)
        print(f"  ✓ 预处理完成: {len(kept_frames)} 帧, {len(transcript.get('segments', []))} 分段")

    transcript_text = transcript_to_text(transcript)
    slide_count = sum(1 for e in events if e["type"] == "slide")
    annot_count = sum(1 for e in events if e["type"] == "annotation")
    print(f"  幻灯片切换: {slide_count}  标注事件: {annot_count}")
    print(f"  逐字稿: {len(transcript_text):,} 字符")

    # ── Phase 2: Build input parts ────────────────────────
    print("\n" + "-" * 40)
    print("  Phase 2: 构建模型输入")
    print("-" * 40 + "\n")

    parts = [PROMPT_TEXT, transcript_text]
    for fp in kept_frames:
        parts.append(frame_marker(fp, events))
        parts.append(types.Part(
            inline_data=types.Blob(mime_type="image/jpeg", data=fp.read_bytes())
        ))
    print(f"  输入块: {len(parts)} (1 prompt + 1 transcript + {len(kept_frames)} 帧 × 2)")

    # ── Phase 3: Gemini ───────────────────────────────────
    print("\n" + "-" * 40)
    print("  Phase 3: Gemini 合成")
    print("-" * 40 + "\n")

    gemini_api_key = os.environ["OPENCLAW_GOOGLE_API_KEY"]
    gemini_client = genai.Client(
        api_key=gemini_api_key,
        http_options=types.HttpOptions(timeout=3600000),
    )

    gemini_text = call_gemini(
        gemini_client, parts,
        label=f"Gemini {VIDEO_STEM[:25]}",
        model=GEMINI_MODEL,
        thinking_budget=8192,
    )

    if gemini_text:
        with open(GEMINI_OUTPUT, "w", encoding="utf-8") as f:
            f.write(f"# {VIDEO_STEM}\n\n")
            f.write(gemini_text.rstrip())
            f.write(_transcript_appendix(transcript_text))
        print(f"  ✓ Gemini 输出: {GEMINI_OUTPUT.name} ({len(gemini_text):,} 字符)")
    else:
        print("  ✗ Gemini 合成失败")
        GEMINI_OUTPUT.write_text(f"# {VIDEO_STEM}\n\n> Gemini 合成失败\n", encoding="utf-8")

    # ── Phase 4: Qwen (分窗合成) ──────────────────────────
    print("\n" + "-" * 40)
    print("  Phase 4: Qwen 分窗合成")
    print("-" * 40 + "\n")

    qwen_api_key = os.environ["DASHSCOPE_API_KEY"]
    qwen_client = OpenAI(
        api_key=qwen_api_key,
        base_url=DASHSCOPE_BASE_URL,
    )

    # Build windows: each ≤ QWEN_MAX_FRAMES, with overlap for continuity.
    # Prioritize slide/annotation frames; context frames fill remaining slots.
    total_frames = len(kept_frames)
    if total_frames > QWEN_MAX_FRAMES:
        # Sort frames by priority: slide > annotation > context
        def _frame_priority(fp):
            marker = frame_marker(fp, events)
            if "type=slide" in marker:
                return 0
            if "type=annotation" in marker:
                return 1
            return 2

        sorted_frames = sorted(kept_frames, key=_frame_priority)
        # Build windows from prioritized frames, then re-sort each window by timestamp
        n_windows = (total_frames + QWEN_MAX_FRAMES - 1) // QWEN_MAX_FRAMES
        window_size = (total_frames + n_windows - 1) // n_windows  # ceiling division
        # Overlap: 10% of window for continuity
        overlap = int(window_size * 0.10)
        overlap = max(0, min(overlap, window_size // 3))

        windows = []
        start_idx = 0
        for wi in range(n_windows):
            end_idx = min(total_frames, start_idx + window_size)
            window_fps = sorted_frames[start_idx:end_idx]
            # Re-sort by natural order (timestamp) within each window
            window_fps.sort(key=lambda fp: int(frame_marker(fp, events).split("[")[1].split("]")[0].replace(":", "")) if "[" in frame_marker(fp, events) else 0)
            windows.append(window_fps)
            # Next window starts with overlap
            start_idx = max(start_idx, end_idx - overlap)

        print(f"  分窗策略: {total_frames} 帧 → {len(windows)} 个窗口")
        for wi, wf in enumerate(windows):
            print(f"    Window {wi+1}: {len(wf)} 帧")
    else:
        windows = [kept_frames]
        print(f"  帧数 {total_frames} ≤ {QWEN_MAX_FRAMES}，无需分窗")

    # ── Pass 1: Window-level synthesis ──
    WINDOW_PROMPT = """# 角色与目标
你是一个顶级的知识库数据提取专家。我将提供一段视频**片段**的逐字稿和关键帧截图，请提取转化为一份详尽的结构化分析笔记。

# 输入说明
- 这是完整视频的一个时间片段。请只聚焦于本片段覆盖的时间范围。
- 逐字稿可能包含前后片段的内容作为上下文参考。
- 关键帧按时间顺序排列，包含幻灯片切换和画笔标注。

# 输出要求
请输出以下结构的分析笔记（Markdown）：

## 片段摘要
- 时间范围、核心主题、关键人物/实体

## 知识点提炼
- 本片段中出现的核心概念、术语及其定义
- 重要的操作步骤、配置参数

## 关键叙事
- 按时间线记录讲者的核心论点、论证过程和案例
- 保留重要的原话/金句（加引号）
- 描述屏幕上的视觉内容（PPT、代码、界面操作等）

## 遗留线索
- 本片段末尾未完成的话题、提到的后续计划"""
    window_notes = []
    window_success = []
    qwen_total_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    window_count = len(windows)
    for wi, wf in enumerate(windows):
        wlabel = f"Qwen-W{wi+1}/{window_count} {VIDEO_STEM[:15]}"
        print(f"\n  [{wlabel}] 发送 {len(wf)} 帧...")

        w_parts = [WINDOW_PROMPT, transcript_text]
        for fp in wf:
            w_parts.append(frame_marker(fp, events))
            w_parts.append(types.Part(
                inline_data=types.Blob(mime_type="image/jpeg", data=fp.read_bytes())
            ))

        w_result = call_qwen(
            qwen_client, w_parts,
            label=wlabel,
            model=QWEN_MODEL,
            enable_thinking=True,
            thinking_budget=4096,
            max_tokens=48000,
            max_retries=3,
        )
        w_text = w_result.get("text") if isinstance(w_result, dict) else None
        w_ok = bool(w_text)
        window_success.append(w_ok)
        if w_ok:
            window_notes.append(w_text)
            w_usage = w_result.get("usage", {})
            qwen_total_usage["input_tokens"] += w_usage.get("input_tokens", 0)
            qwen_total_usage["output_tokens"] += w_usage.get("output_tokens", 0)
            qwen_total_usage["total_tokens"] += w_usage.get("total_tokens", 0)
            print(f"  [{wlabel}] ✓ {len(w_text):,} 字符")
        else:
            print(f"  [{wlabel}] ✗ 失败，跳过此窗口")

    if not any(window_success):
        print("  ✗ 所有窗口合成失败")
        QWEN_OUTPUT.write_text(f"# {VIDEO_STEM}\n\n> Qwen 分窗合成全部失败\n", encoding="utf-8")
        qwen_text = None
    elif window_count == 1:
        qwen_text = window_notes[0]
    else:
        # ── Pass 2: Final assembly ──
        print(f"\n  [Qwen-Assembly] 合并 {window_count} 个窗口笔记...")
        ASSEMBLY_PROMPT = f"""# 角色与目标
你是一个顶级的知识库文档整合专家。我有一段完整视频的 {window_count} 个片段分析笔记，请将它们整合为一份**统一、连贯、无重复**的 NotebookLM 就绪 Markdown 文档。

# 整合原则
1. **去重合并**: 重叠内容合并为一段，不要出现重复的论点或术语定义
2. **统一结构**: 按视频时间线重新组织为逻辑章节
3. **消除窗口痕迹**: 不要出现"片段1""窗口1"等字样，读者不应感知到分窗的存在
4. **保留所有细节**: 操作步骤、配置参数、关键原话必须全部保留
5. **章节时间戳**: 使用原始视频时间戳（HH:MM:SS）

# 必须输出的 Markdown 结构

## 1. 视频元数据
- **推测主题：**
- **核心关键词：**
- **适用受众/场景：**

## 2. 核心知识字典（Glossary）
（提取全部片段中反复出现的核心概念，合并去重，3-8 条）

## 3. 详尽内容解析（按时间线）
（按逻辑章节组织，每个章节包含：核心论点、详细展开、视觉/屏幕内容、重要金句/原话）

## 4. 遗留问题与下一步行动（如有）

# 片段笔记
"""
        for i, note in enumerate(window_notes):
            ASSEMBLY_PROMPT += f"\n\n---\n## 片段 {i+1} 笔记\n\n{note}"

        # Final assembly: text-only (no frames), uses full transcript as reference
        assembly_parts = [ASSEMBLY_PROMPT]
        assembly_result = call_qwen(
            qwen_client, assembly_parts,
            label=f"Qwen-Assembly {VIDEO_STEM[:20]}",
            model=QWEN_MODEL,
            enable_thinking=True,
            thinking_budget=8192,
            max_tokens=64000,
            max_retries=3,
        )
        qwen_text = assembly_result.get("text") if isinstance(assembly_result, dict) else None
        if qwen_text:
            a_usage = assembly_result.get("usage", {})
            qwen_total_usage["input_tokens"] += a_usage.get("input_tokens", 0)
            qwen_total_usage["output_tokens"] += a_usage.get("output_tokens", 0)
            qwen_total_usage["total_tokens"] += a_usage.get("total_tokens", 0)
            print(f"  [Qwen-Assembly] ✓ {len(qwen_text):,} 字符")
        else:
            print("  [Qwen-Assembly] ✗ 最终拼合失败，回退到串联输出")
            qwen_text = "\n\n---\n\n".join(window_notes)

    # ── Phase 4b: Qwen QC + 确定性附录 ──────────────────────
    qwen_qc: dict = {}
    if qwen_text and window_notes:
        print("\n  [QC] 检测压缩比 + 追加确定性附录...")
        facts = extract_qwen_critical_facts(window_notes)
        blocks = extract_qwen_narrative_blocks(window_notes)
        qwen_text, _fact_qc = ensure_qwen_critical_fact_appendix(qwen_text, facts)
        qwen_text, _narr_qc = ensure_qwen_narrative_appendix(qwen_text, blocks, transcript_text)
        qwen_qc = check_qwen_notebooklm_quality(qwen_text, transcript_text, {})
        ratio = qwen_qc["metrics"]["body_transcript_ratio"]
        if qwen_qc["warnings"]:
            for w in qwen_qc["warnings"]:
                print(f"  [QC⚠] {w}")
        else:
            print(f"  [QC✓] body/transcript={ratio:.3f}, chars={qwen_qc['metrics']['body_chars']:,}")
        if _fact_qc.get("appended"):
            print(f"  [QC+] 追加关键事实索引: {_fact_qc['appended_facts']} 条")
        if _narr_qc.get("appended"):
            print(f"  [QC+] 追加叙事证据附录: {_narr_qc['appended_blocks']} 块")

    if qwen_text:
        with open(QWEN_OUTPUT, "w", encoding="utf-8") as f:
            f.write(f"# {VIDEO_STEM}\n\n")
            f.write(qwen_text.rstrip())
            f.write(_transcript_appendix(transcript_text))
        print(f"\n  ✓ Qwen 输出: {QWEN_OUTPUT.name} ({len(qwen_text):,} 字符)")
    else:
        print("  ✗ Qwen 合成失败")
        QWEN_OUTPUT.write_text(f"# {VIDEO_STEM}\n\n> Qwen 合成失败\n", encoding="utf-8")

    # ── Phase 5: Manifest ─────────────────────────────────
    print("\n" + "-" * 40)
    print("  Phase 5: 生成验证清单")
    print("-" * 40 + "\n")

    manifest = {
        "video_stem": VIDEO_STEM,
        "date": date.today().isoformat(),
        "models": {
            "gemini": {
                "model": GEMINI_MODEL,
                "output": str(GEMINI_OUTPUT.name),
                "chars": len(gemini_text) if gemini_text else 0,
                "success": bool(gemini_text),
            },
            "qwen": {
                "model": QWEN_MODEL,
                "output": str(QWEN_OUTPUT.name),
                "chars": len(qwen_text) if qwen_text else 0,
                "success": bool(qwen_text),
                "windows": window_count,
                "window_success": sum(window_success),
                "usage": qwen_total_usage,
                "qc_warnings": qwen_qc.get("warnings"),
                "qc_metrics": qwen_qc.get("metrics"),
            },
        },
        "preprocessing": {
            "frames": len(kept_frames),
            "segments": len(transcript.get("segments", [])),
            "transcript_chars": len(transcript_text),
            "slide_count": slide_count,
            "annotation_count": annot_count,
            "backend_used": transcript.get("backend_used"),
        },
    }
    with open(MANIFEST_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"  ✓ 清单: {MANIFEST_OUTPUT.name}")

    # ── Summary ───────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  双模型验证完成!")
    print("=" * 60)
    print(f"  Gemini: {'✓' if gemini_text else '✗'} {GEMINI_OUTPUT.name} ({len(gemini_text or ''):,} 字符)")
    print(f"  Qwen:   {'✓' if qwen_text else '✗'} {QWEN_OUTPUT.name} ({len(qwen_text or ''):,} 字符)")
    print(f"  清单:   {MANIFEST_OUTPUT.name}")
    print("=" * 60)


if __name__ == "__main__":
    main()
