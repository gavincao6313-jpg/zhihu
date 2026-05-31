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
    format_qwen_critical_facts_for_prompt, format_qwen_narrative_blocks_for_prompt,
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


# ── Qwen prompts (aligned with scripts/build_stream_markdown.py) ──────────────

_QWEN_NOTEBOOKLM_PROMPT = """
# 角色与目标
你是一个面向 NotebookLM / 长文本 RAG 的中文直播知识库文档生成器。你的任务不是写高管摘要，也不是帮读者节省篇幅，而是把输入的完整逐字稿和关键帧截图转成一份**可检索、可追溯、细节保真的 Markdown 知识库源文档**。

# 最高优先级：禁止过度压缩
Qwen 容易把口语内容整理成短 bullet points。当前任务明确禁止这种做法。请保留讲师的原生语境、案例链路、具体数字、打分、提示词、屏幕文字和重要原话。宁可输出更长，也不要把长案例压缩成一句概括。

# 必须保留的高价值证据
- 讲师现场展示或口述的 Prompt / 提示词 / 配置 / 代码 / 命令 / UI 文案，必须原样或近原样保留，并用 Markdown 代码块包裹。
- 具体案例的因果链路必须完整保留：问题是什么、讲师怎么判断、改了什么、为什么这样改、效果如何。
- 具体数字、时间、评分、比例、工具名、人名和课程名不能省略。
- 视觉/屏幕内容不能只写"展示了截图"。要描述截图上出现的标题、表格、红字、圈注、代码、配置项或演示结果。

# 输入说明
- **逐字稿**: 带全局时间戳的中文直播转写。
- **关键帧**: 按时间排序的视频截图，包含幻灯片切换、画笔标注、代码/配置界面。

# 必须输出的 Markdown 结构

必须从 H1 开始，不能省略标题：

# （给这场视频起一个准确、具体的中文标题）

## 1. 视频元数据
- **推测主题：**
- **核心关键词：** 5-12 个关键词，优先保留原始术语。
- **适用受众/场景：**

## 2. 核心知识字典（Glossary）
请提炼 5-8 个概念。定义要清晰，但不要牺牲细节。

## 3. 详尽内容解析
请按真实时间线拆分章节。每个章节标题必须独立成行，并使用：

### [HH:MM:SS - HH:MM:SS] 章节标题

每个章节必须包含以下四项，不能缺项：
- **核心论点：** 本段结论。
- **详细展开：** 详尽保留讲师解释、案例背景、判断过程、操作步骤、数字、评分、因果关系。不要只列短 bullet。
- **视觉/屏幕内容：** 详细转写屏幕信息。若出现 Prompt、配置、代码、命令、UI 文案，请用代码块保留。
- **重要金句/原话：** 1-3 句原话或近原话。

## 4. 遗留问题与下一步行动
记录视频结尾、课程安排、待办事项或未解决问题。

# 质量自检
输出前自检：
1. 是否有 H1 标题？
2. 是否保留了 Prompt/提示词/配置/代码块？
3. 是否保留了具体案例的细节、数字、评分和原话？
4. 是否每个时间线章节都有视觉/屏幕内容？
5. 是否避免了"高管摘要"式过度压缩？

如果不确定某个细节是否重要，保留它。NotebookLM 后续检索依赖这些细节。
"""

_QWEN_WINDOW_NOTE_PROMPT = """
# 角色与目标
你是 NotebookLM 知识库的"窗口级证据采集员"。我会提供长视频中的一个时间窗口：本窗口逐字稿 + 本窗口关键帧。你的任务是生成**保真窗口笔记**，不是最终文章，也不是摘要。

# 最高优先级
禁止高管摘要化，禁止把长案例压缩成一句话。请捕获本窗口中所有后续 RAG 检索可能需要的细节。

# 必须保留
- Prompt / 提示词 / 配置 / 代码 / 命令 / UI 文案：用 Markdown 代码块保存。
- 具体案例链路：问题、判断、修改、原因、效果。
- 具体数字和标签：评分、比例、时长、工具名、人名、项目名。
- 视觉证据：截图/幻灯片/群聊/产品界面上的标题、表格、红字、圈注、代码、配置项。
- 讲师原话或近原话：尤其是判断标准、金句、风险提示。

# 严厉指令：数字与时间句强制留存
看到任何包含具体数字、年份、年龄、百分比、时长（秒/分钟）、金额、积分、分数的句子，必须原文或近原文保留。

# 输出格式
请严格使用以下结构：

## Window Metadata
- **时间范围：** [HH:MM:SS - HH:MM:SS]
- **窗口序号：**
- **覆盖帧数：**

## Faithful Notes
按时间顺序记录本窗口信息。不要为了简洁而删除细节。

## Critical Number Sentences
逐条列出本窗口所有包含年份、年龄、百分比、时长、金额、积分、分数的完整句子。没有则写"未发现"。

## Narrative Evidence Blocks
保留本窗口中 2-6 段最有 NotebookLM 检索价值的长叙事证据块。每段 300-800 字，尽量接近讲师原始表达，不要改成思维导图短句。

每段格式：
### Narrative Block [HH:MM:SS - HH:MM:SS] 标题
原文或近原文长段内容。

## Preserved Prompts / Code / Config
如果本窗口出现提示词、代码、配置、命令或 UI 文案，必须放在这里并用代码块保留。没有则写"未发现"。

## Visual Evidence
逐条记录关键视觉证据，包括时间戳和屏幕内容。

## Quotes
记录 3-8 条重要原话或近原话。

## Merge Hints
写给最终组装步骤的提示：本窗口应归入哪个章节、与前后窗口的关系、哪些内容不能丢。
"""

_QWEN_FINAL_ASSEMBLY_PROMPT = """
# 角色与目标
你是 NotebookLM / 长文本 RAG 知识库文档的最终组装器。你将收到：
1. 由程序从 Qwen 窗口笔记中确定性抽取出的 Critical Facts Checklist；
2. 由程序从 Qwen 窗口笔记中确定性抽取出的 Narrative Evidence Blocks；
3. 多个 Qwen 窗口级保真笔记。

# 关键规则
- 不能把窗口笔记压缩成高管摘要。
- 不能删除窗口笔记中保存的 Prompt、代码块、配置、UI 文案、案例打分、数字、金句和视觉证据。
- Critical Facts Checklist 中的每一项都必须出现在最终正文、技术资产附录或关键事实索引中。
- Narrative Evidence Blocks 是防止长文叙事被压缩的保底证据。最终正文必须吸收这些长段的细节和语气。
- 章节必须按真实时间线线性展开，禁止出现重叠时间段。
- 每个输入窗口必须对应至少一个独立章节。最终章节数 ≥ 输入窗口数。
- Glossary 可以更清晰，但正文必须保留窗口笔记中的丰富细节。

# 必须输出
# （准确具体的中文标题）

## 1. 视频元数据
- **推测主题：**
- **核心关键词：**
- **适用受众/场景：**

## 2. 核心知识字典（Glossary）
提炼 5-10 个概念，定义清晰且保留细节。

## 3. 详尽内容解析
章节标题必须为：
### [HH:MM:SS - HH:MM:SS] 章节标题

每章必须包含：
- **核心论点：**
- **详细展开：**
- **叙事证据摘录：** 引用或近原文保留本章对应的长叙事证据，不少于 150 字；如果本章没有叙事证据则写"本章无长叙事证据"。
- **视觉/屏幕内容：**
- **重要金句/原话：**

## 4. 遗留问题与下一步行动

## 5. 技术资产附录：Prompts / Code / Config
必须集中保留所有窗口笔记中的 Prompt、代码块、配置、命令和 UI 文案。每条资产要标明来源时间或窗口编号。不要只写概括，必须保留原文或近原文代码块。

## 6. 叙事证据附录
集中保留最重要的长叙事证据块。每条要标明来源窗口和时间范围。这个附录用于 NotebookLM 检索，不要压缩成短句。

## 7. 关键事实索引
集中列出 Critical Facts Checklist 中的关键数字、年份、年龄、百分比、时长、金额、积分、评分、工具名和 Prompt 关键词。每条要标明来源窗口，并保留上下文短句。

# 自检
输出前确认：H1 存在；所有窗口都有内容进入正文；章节数 ≥ 输入窗口数；Critical Facts Checklist 全部落地；Prompt/代码块没有丢；技术资产附录存在；关键事实索引存在；章节时间线不重叠；正文不是短摘要。

# 隐藏覆盖标记（必须输出）
在文档最后一行添加 HTML 注释，列出已纳入最终正文的窗口编号，格式必须严格为：
<!-- qwen_window_coverage: 1,2,3 -->
"""


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
    # Single-window: use one-shot NotebookLM prompt (output is final format directly).
    # Multi-window: use structured window-note prompt → assembly pass converts to final format.
    window_notes = []
    window_success = []
    qwen_total_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    window_count = len(windows)
    w_prompt = _QWEN_NOTEBOOKLM_PROMPT if window_count == 1 else _QWEN_WINDOW_NOTE_PROMPT
    for wi, wf in enumerate(windows):
        wlabel = f"Qwen-W{wi+1}/{window_count} {VIDEO_STEM[:15]}"
        print(f"\n  [{wlabel}] 发送 {len(wf)} 帧...")

        w_parts = [w_prompt, transcript_text]
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
        _asm_facts = extract_qwen_critical_facts(window_notes)
        _asm_blocks = extract_qwen_narrative_blocks(window_notes)
        _constraint = f"约束：本次输入包含 {window_count} 个窗口笔记，最终章节数必须 ≥ {window_count}。\n\n"
        ASSEMBLY_PROMPT = (
            _constraint
            + format_qwen_critical_facts_for_prompt(_asm_facts) + "\n\n"
            + format_qwen_narrative_blocks_for_prompt(_asm_blocks) + "\n\n"
            + _QWEN_FINAL_ASSEMBLY_PROMPT
        )
        for i, note in enumerate(window_notes, start=1):
            ASSEMBLY_PROMPT += f"\n\n---\n## 窗口 {i} 笔记\n\n{note}"

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
