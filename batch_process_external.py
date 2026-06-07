"""Batch process MP4 videos from an external directory through the
ASR → keyframes → AI synthesis pipeline.

Usage:
    cd d:\zhihu\zhihu_file
    .venv-sensevoice\Scripts\python.exe batch_process_external.py --dry-run
    .venv-sensevoice\Scripts\python.exe batch_process_external.py --status
    .venv-sensevoice\Scripts\python.exe batch_process_external.py --max-videos 1
    .venv-sensevoice\Scripts\python.exe batch_process_external.py

Qwen prompts are duplicated from run_dual_model.py (lines 70-232).
If those prompts change upstream, sync them here.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.chdir(str(Path(__file__).parent))

# Fix Windows GBK encoding
sys.stdout.reconfigure(encoding="utf-8")

from zhihuTTS_video import (
    extract_keyframes,
    transcribe_audio_chunked,
    transcript_to_text,
    frame_marker,
    TRANSCRIBE_CHUNK_DURATION_S,
)
from zhihuTTS import (
    PROMPT_TEXT as GEMINI_PROMPT,
    MARKDOWNS_DIR,
    tprint,
    _save_preprocess_cache,
    _load_preprocess_cache,
    TRANSCRIPT_APPENDIX_HEADING,
)
from utils import (
    call_gemini,
    call_qwen,
    extract_qwen_critical_facts,
    extract_qwen_narrative_blocks,
    format_qwen_critical_facts_for_prompt,
    format_qwen_narrative_blocks_for_prompt,
    ensure_qwen_critical_fact_appendix,
    ensure_qwen_narrative_appendix,
    check_qwen_notebooklm_quality,
)
from google import genai
from google.genai import types
from openai import OpenAI

# ── Config ──────────────────────────────────────────────────

DEFAULT_SOURCE_DIR = Path(r"E:\AI产品经理课")
DEFAULT_OUTPUT_DIR = MARKDOWNS_DIR / "batch"
BATCH_PROGRESS_FILE = Path(__file__).parent / ".progress_batch.json"

DEFAULT_DURATION_THRESHOLD_S = 9000       # 2.5h — Gemini ≤ this, Qwen >
DEFAULT_DAILY_LIMIT_GEMINI = 20
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
QWEN_MODEL = os.environ.get("QWEN_MODEL", "qwen3.7-plus")
QWEN_MAX_FRAMES = 250
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

VIDEO_EXTENSIONS = (".mp4", ".webm", ".m4v", ".mov", ".avi", ".mkv", ".mpeg")


# ── Qwen prompts (synced from run_dual_model.py lines 70-232) ─────

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


# ── Helpers ──────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _transcript_appendix(transcript_text: str) -> str:
    return (
        "\n\n---\n\n"
        f"{TRANSCRIPT_APPENDIX_HEADING}\n\n"
        "以下为本地转写得到的完整文字记录，保留时间戳，便于检索、复盘和重新生成摘要。\n\n"
        "```text\n"
        f"{transcript_text.rstrip()}\n"
        "```\n"
    )


def _safe_name(stem: str) -> str:
    """Remove characters unsafe for file paths."""
    return "".join(c for c in stem if c not in r'<>:"/\|?*')


# ── Duration & Discovery ────────────────────────────────────

def get_video_duration(video_path: Path) -> float | None:
    """Return video duration in seconds via ffprobe.  None on failure."""
    try:
        result = subprocess.run(
            ["ffprobe", "-hide_banner", "-v", "error",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1",
             str(video_path)],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        pass
    return None


def fmt_duration(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}h{m:02d}m"


def discover_external_videos(source_dir: Path) -> dict[str, Path]:
    """Scan source_dir for media files, return {stem: path} sorted by stem."""
    videos: dict[str, Path] = {}
    for ext in VIDEO_EXTENSIONS:
        for p in sorted(source_dir.glob(f"*{ext}")):
            videos[p.stem] = p
    return dict(sorted(videos.items()))


def route_provider(duration_s: float, threshold_s: int) -> str:
    """Return 'gemini' or 'qwen' based on duration."""
    return "gemini" if duration_s <= threshold_s else "qwen"


# ── Progress ─────────────────────────────────────────────────

def load_batch_progress() -> dict:
    """Load or initialize batch progress."""
    if BATCH_PROGRESS_FILE.exists():
        try:
            with open(BATCH_PROGRESS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            print("[warn] 进度文件损坏，重新初始化")
    return {
        "source_dir": str(DEFAULT_SOURCE_DIR),
        "output_dir": str(DEFAULT_OUTPUT_DIR),
        "videos": {},
        "quota": {},
        "last_run": None,
    }


def save_batch_progress(progress: dict) -> None:
    """Atomic write batch progress."""
    tmp = BATCH_PROGRESS_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)
    tmp.replace(BATCH_PROGRESS_FILE)


def print_batch_status(progress: dict, videos: dict) -> None:
    """Print formatted batch processing status."""
    done = sum(1 for v in progress["videos"].values() if v["status"] == "done")
    failed = sum(1 for v in progress["videos"].values() if v["status"] == "failed")
    pending = sum(1 for v in progress["videos"].values() if v["status"] == "pending")
    unknown = len(videos) - len(progress["videos"])

    print("=" * 56)
    print("  批处理进度")
    print("=" * 56)
    print(f"  总计: {len(videos)}  |  完成: {done}  |  失败: {failed}  |  待处理: {pending}  |  新: {unknown}")
    print(f"  上次运行: {progress.get('last_run') or '从未'}")
    for today, q in sorted(progress.get("quota", {}).items()):
        g = q.get("gemini_calls", 0)
        qn = q.get("qwen_calls", 0)
        print(f"  {today}: Gemini={g}  Qwen={qn}")


# ── Single-video Processing ─────────────────────────────────

def _preprocess_video(video_path: Path, video_label: str):
    """Run keyframe extraction + SenseVoice transcription. Uses cache if valid."""
    cached = _load_preprocess_cache(video_path, video_label)
    if cached:
        events, kept_frames, transcript = cached
        print(f"  ✓ 命中预处理缓存: {len(kept_frames)} 帧, {len(transcript.get('segments', []))} 分段")
        return events, kept_frames, transcript

    tprint(f"[{video_label}] 提取关键帧 & 转录音频...")
    events, kept_frames = extract_keyframes(video_path)
    transcript = transcribe_audio_chunked(video_path, TRANSCRIBE_CHUNK_DURATION_S)
    _save_preprocess_cache(video_path, events, kept_frames, transcript)
    print(f"  ✓ 预处理完成: {len(kept_frames)} 帧, {len(transcript.get('segments', []))} 分段")
    return events, kept_frames, transcript


def _build_parts(transcript_text: str, kept_frames: list, events: list, prompt: str) -> list:
    """Build model input parts: prompt + transcript + frame markers + frame images."""
    parts = [prompt, transcript_text]
    for fp in kept_frames:
        parts.append(frame_marker(fp, events))
        parts.append(types.Part(
            inline_data=types.Blob(mime_type="image/jpeg", data=fp.read_bytes())
        ))
    return parts


def _process_gemini(gemini_client, parts: list, video_label: str) -> dict:
    """Gemini synthesis path. Returns {text, api_calls, success, failed_stage}."""
    text = call_gemini(
        gemini_client, parts,
        label=f"Gemini {video_label[:25]}",
        model=GEMINI_MODEL,
        thinking_budget=8192,
        max_retries=6,
        max_continuations=20,
    )
    if text:
        return {"text": text, "api_calls": 1, "success": True, "failed_stage": None}
    else:
        return {"text": None, "api_calls": 1, "success": False, "failed_stage": "gemini"}


def _process_qwen(qwen_client, parts: list, video_label: str,
                  transcript_text: str, kept_frames: list, events: list) -> dict:
    """Qwen sliding-window synthesis path. Returns {text, api_calls, success, ...}."""
    total_frames = len(kept_frames)

    # Build windows if needed
    if total_frames > QWEN_MAX_FRAMES:
        def _frame_priority(fp):
            marker = frame_marker(fp, events)
            if "type=slide" in marker:
                return 0
            if "type=annotation" in marker:
                return 1
            return 2

        sorted_frames = sorted(kept_frames, key=_frame_priority)
        n_windows = (total_frames + QWEN_MAX_FRAMES - 1) // QWEN_MAX_FRAMES
        window_size = (total_frames + n_windows - 1) // n_windows
        overlap = max(0, min(int(window_size * 0.10), window_size // 3))

        windows = []
        start_idx = 0
        for _ in range(n_windows):
            end_idx = min(total_frames, start_idx + window_size)
            window_fps = sorted_frames[start_idx:end_idx]
            window_fps.sort(key=lambda fp: (
                int(frame_marker(fp, events).split("[")[1].split("]")[0].replace(":", ""))
                if "[" in frame_marker(fp, events) else 0
            ))
            windows.append(window_fps)
            start_idx = max(start_idx, end_idx - overlap)

        print(f"  分窗策略: {total_frames} 帧 → {len(windows)} 个窗口")
    else:
        windows = [kept_frames]
        print(f"  帧数 {total_frames} ≤ {QWEN_MAX_FRAMES}，无需分窗")

    # Window-level synthesis
    window_notes = []
    window_success = []
    qwen_calls = 0
    window_count = len(windows)
    w_prompt = _QWEN_NOTEBOOKLM_PROMPT if window_count == 1 else _QWEN_WINDOW_NOTE_PROMPT

    for wi, wf in enumerate(windows):
        wlabel = f"Qwen-W{wi+1}/{window_count} {video_label[:15]}"
        print(f"  [{wlabel}] 发送 {len(wf)} 帧...")

        w_parts = [w_prompt, transcript_text]
        for fp in wf:
            w_parts.append(frame_marker(fp, events))
            w_parts.append(types.Part(
                inline_data=types.Blob(mime_type="image/jpeg", data=fp.read_bytes())
            ))

        w_result = call_qwen(
            qwen_client, w_parts,
            label=wlabel, model=QWEN_MODEL,
            enable_thinking=True, thinking_budget=4096,
            max_tokens=48000, max_retries=3,
        )
        qwen_calls += 1
        w_text = w_result.get("text") if isinstance(w_result, dict) else None
        w_ok = bool(w_text)
        window_success.append(w_ok)
        if w_ok:
            window_notes.append(w_text)
            print(f"  [{wlabel}] ✓ {len(w_text):,} 字符")
        else:
            print(f"  [{wlabel}] ✗ 失败，跳过此窗口")

    if not any(window_success):
        return {"text": None, "api_calls": qwen_calls, "success": False, "failed_stage": "qwen-windows"}

    if window_count == 1:
        qwen_text = window_notes[0]
    else:
        # Final assembly
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

        assembly_result = call_qwen(
            qwen_client, [ASSEMBLY_PROMPT],
            label=f"Qwen-Assembly {video_label[:20]}",
            model=QWEN_MODEL, enable_thinking=True, thinking_budget=8192,
            max_tokens=64000, max_retries=3,
        )
        qwen_calls += 1
        qwen_text = assembly_result.get("text") if isinstance(assembly_result, dict) else None
        if qwen_text:
            print(f"  [Qwen-Assembly] ✓ {len(qwen_text):,} 字符")
        else:
            print("  [Qwen-Assembly] ✗ 回退到串联输出")
            qwen_text = "\n\n---\n\n".join(window_notes)

    # QC + deterministic appendices
    if qwen_text and window_notes:
        print("  [QC] 检测压缩比 + 追加确定性附录...")
        facts = extract_qwen_critical_facts(window_notes)
        blocks = extract_qwen_narrative_blocks(window_notes)
        qwen_text, _fact_qc = ensure_qwen_critical_fact_appendix(qwen_text, facts)
        qwen_text, _narr_qc = ensure_qwen_narrative_appendix(qwen_text, blocks, transcript_text)
        qwen_qc = check_qwen_notebooklm_quality(qwen_text, transcript_text, {})
        if qwen_qc.get("warnings"):
            for w in qwen_qc["warnings"]:
                print(f"  [QC⚠] {w}")

    return {"text": qwen_text, "api_calls": qwen_calls, "success": True, "failed_stage": None}


def process_single_video(
    gemini_client,
    qwen_client,
    video_path: Path,
    output_path: Path,
    video_label: str,
    provider: str,
) -> dict:
    """Full pipeline for one video. Returns result dict for progress tracking."""
    print(f"\n{'=' * 56}")
    print(f"  [{video_label}] 开始处理 (provider={provider})")
    print(f"{'=' * 56}")

    result = {
        "provider": provider,
        "api_calls": 0,
        "success": False,
        "failed_stage": None,
        "output": str(output_path.name),
    }

    try:
        # Phase 1: Preprocess
        print("\n  [Phase 1] 预处理（关键帧 + 语音转写）...")
        events, kept_frames, transcript = _preprocess_video(video_path, video_label)
        transcript_text = transcript_to_text(transcript)
        slide_count = sum(1 for e in events if e["type"] == "slide")
        annot_count = sum(1 for e in events if e["type"] == "annotation")
        print(f"  幻灯片: {slide_count}  标注: {annot_count}  逐字稿: {len(transcript_text):,} 字符")

        # Phase 2: Build input
        print("\n  [Phase 2] 构建模型输入...")
        prompt = GEMINI_PROMPT if provider == "gemini" else _QWEN_NOTEBOOKLM_PROMPT
        parts = _build_parts(transcript_text, kept_frames, events, prompt)
        print(f"  输入块: {len(parts)} (1 prompt + 1 transcript + {len(kept_frames)} 帧 × 2)")

        # Phase 3: Synthesize
        print(f"\n  [Phase 3] {provider.upper()} 合成...")
        if provider == "gemini":
            synth_result = _process_gemini(gemini_client, parts, video_label)
        else:
            synth_result = _process_qwen(
                qwen_client, parts, video_label,
                transcript_text, kept_frames, events,
            )

        result["api_calls"] = synth_result["api_calls"]
        result["success"] = synth_result["success"]
        result["failed_stage"] = synth_result["failed_stage"]

        # Phase 4: Write output
        if synth_result["text"]:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(f"# {video_path.stem}\n\n")
                f.write(synth_result["text"].rstrip())
                f.write(_transcript_appendix(transcript_text))
            print(f"  ✓ 输出: {output_path.name} ({len(synth_result['text']):,} 字符)")
        else:
            print(f"  ✗ {provider.upper()} 合成失败")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                f"# {video_path.stem}\n\n> {provider.upper()} 合成失败\n\n"
                f"逐字稿长度: {len(transcript_text):,} 字符\n",
                encoding="utf-8",
            )

    except Exception as exc:
        print(f"  ✗ 处理异常: {exc}")
        result["success"] = False
        result["failed_stage"] = result["failed_stage"] or "exception"
        # Write a partial output so the video is marked as attempted
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                f"# {video_path.stem}\n\n> 处理失败: {exc}\n",
                encoding="utf-8",
            )
        except Exception:
            pass

    return result


# ── Orchestration ───────────────────────────────────────────

def dry_run(source_dir: Path, threshold_s: int, daily_limit_gemini: int) -> None:
    """Scan all videos, estimate durations, show provider assignment."""
    videos = discover_external_videos(source_dir)
    if not videos:
        print(f"未在 {source_dir} 找到视频文件")
        return

    print("=" * 70)
    print(f"  批处理 Dry Run: {source_dir}")
    print("=" * 70)
    print(f"  时长阈值: {fmt_duration(threshold_s)} ({threshold_s}s)")
    print(f"  Gemini 日配额: {daily_limit_gemini} 次")
    print()

    rows = []
    gemini_count = qwen_count = 0
    gemini_est = qwen_est = 0

    for i, (stem, vpath) in enumerate(videos.items(), 1):
        label = f"{i}/{len(videos)}"
        dur = get_video_duration(vpath)
        if dur is None:
            rows.append((i, stem, "?", "???", "???"))
            continue

        provider = route_provider(dur, threshold_s)
        est_calls = 1 if provider == "gemini" else "2-5"
        rows.append((i, stem, fmt_duration(dur), provider, str(est_calls)))

        if provider == "gemini":
            gemini_count += 1
            gemini_est += 1  # conservative: assume no continuations
        else:
            qwen_count += 1
            qwen_est += 3  # rough average for sliding window

    # Print table
    print(f"  {'#':<4} {'Stem':<40} {'Duration':<8} {'Provider':<8} {'Est. Calls'}")
    print(f"  {'─'*3:<4} {'─'*40:<40} {'─'*8:<8} {'─'*8:<8} {'─'*10}")
    for r in rows:
        print(f"  {r[0]:<4} {r[1][:40]:<40} {r[2]:<8} {r[3]:<8} {r[4]}")

    print()
    print(f"  Gemini 视频: {gemini_count}  预估调用: {gemini_est}  预估天数: {max(1, gemini_est // daily_limit_gemini + 1)}")
    print(f"  Qwen 视频:   {qwen_count}  预估调用: {qwen_est}")
    print("=" * 70)


def process_batch(args: argparse.Namespace) -> None:
    """Main orchestrator."""
    source_dir = Path(args.source_dir)
    if not source_dir.is_dir():
        print(f"错误: 源目录不存在 — {source_dir}")
        sys.exit(1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Discover videos
    videos = discover_external_videos(source_dir)
    if not videos:
        print(f"未在 {source_dir} 找到视频文件")
        return

    # Load progress
    progress = load_batch_progress()
    progress["source_dir"] = str(source_dir)
    progress["output_dir"] = str(output_dir)

    if args.status:
        print_batch_status(progress, videos)
        return

    # Probe durations for new videos
    print("探测视频时长...")
    for stem, vpath in videos.items():
        if stem in progress["videos"] and "duration_s" in progress["videos"][stem]:
            continue
        dur = get_video_duration(vpath)
        if dur is None:
            print(f"  ⚠ {stem}: 无法探测时长，标记为失败")
            progress["videos"][stem] = {
                "status": "failed", "provider": "unknown",
                "duration_s": None, "api_calls": 0,
                "processed": _now_iso(), "failed_stage": "duration_probe",
                "output": "",
            }
        else:
            provider = route_provider(dur, args.duration_threshold)
            progress["videos"].setdefault(stem, {})
            progress["videos"][stem]["duration_s"] = dur
            progress["videos"][stem]["provider"] = provider
            progress["videos"][stem].setdefault("status", "pending")
            print(f"  {stem[:50]}: {fmt_duration(dur)} → {provider}")
    save_batch_progress(progress)

    # Determine pending videos
    pending = {}
    for stem in videos:
        entry = progress["videos"].get(stem, {})
        status = entry.get("status", "pending")
        if status == "done":
            continue
        if status == "failed" and not args.retry_failed:
            continue
        pending[stem] = videos[stem]

    if not pending:
        print("\n✓ 所有视频已处理完毕")
        return

    # Apply max-videos limit
    if args.max_videos and args.max_videos > 0:
        pending_items = list(pending.items())[:args.max_videos]
        pending = dict(pending_items)
        print(f"\n限制处理数量: {len(pending)}")

    print(f"\n待处理: {len(pending)} 个视频")

    # Daily quota check
    today = date.today().isoformat()
    daily = progress["quota"].setdefault(today, {"gemini_calls": 0, "qwen_calls": 0})
    gemini_used_today = daily["gemini_calls"]
    gemini_remaining = max(0, args.daily_limit_gemini - gemini_used_today)
    print(f"今日 Gemini 配额: {gemini_used_today}/{args.daily_limit_gemini} 已用, {gemini_remaining} 剩余")

    if gemini_remaining <= 0:
        # Check if any pending videos are Gemini-routed
        gemini_pending = sum(
            1 for s in pending
            if progress["videos"].get(s, {}).get("provider") == "gemini"
        )
        if gemini_pending > 0:
            print(f"⚠ 今日 Gemini 配额已用完，将跳过 {gemini_pending} 个 Gemini 视频")

    # Initialize API clients
    print("\n初始化 API 客户端...")
    gemini_api_key = os.environ.get("OPENCLAW_GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    qwen_api_key = os.environ.get("DASHSCOPE_API_KEY")

    gemini_client = None
    if gemini_api_key:
        http_opts = types.HttpOptions(
            timeout=3600000,
            base_url=os.environ.get("GEMINI_BASE_URL") or None,
            api_version=os.environ.get("GEMINI_API_VERSION", "v1beta") if os.environ.get("GEMINI_BASE_URL") else None,
        )
        gemini_client = genai.Client(api_key=gemini_api_key, http_options=http_opts)
        print(f"  Gemini: ✓ ({GEMINI_MODEL})")
    else:
        print("  Gemini: ✗ 无 API Key — Gemini 视频将被跳过")

    qwen_client = None
    if qwen_api_key:
        qwen_client = OpenAI(api_key=qwen_api_key, base_url=DASHSCOPE_BASE_URL)
        print(f"  Qwen: ✓ ({QWEN_MODEL})")
    else:
        print("  Qwen: ✗ 无 API Key — Qwen 视频将被跳过")

    # Process loop
    processed = 0
    success_count = 0
    for i, (stem, vpath) in enumerate(pending.items(), 1):
        entry = progress["videos"].get(stem, {})
        provider = entry.get("provider", "gemini")

        # Quota gate for Gemini
        if provider == "gemini":
            daily = progress["quota"].setdefault(today, {"gemini_calls": 0, "qwen_calls": 0})
            if daily["gemini_calls"] >= args.daily_limit_gemini:
                print(f"\n⏸  [{i}/{len(pending)}] {stem[:50]} — Gemini 配额不足，今日跳过")
                continue
            if gemini_client is None:
                print(f"\n⏸  [{i}/{len(pending)}] {stem[:50]} — 无 Gemini API Key，跳过")
                continue

        if provider == "qwen" and qwen_client is None:
            print(f"\n⏸  [{i}/{len(pending)}] {stem[:50]} — 无 Qwen API Key，跳过")
            continue

        video_label = f"{i}/{len(pending)} {stem[:30]}"
        output_path = output_dir / f"{_safe_name(stem)}.md"

        result = process_single_video(
            gemini_client, qwen_client, vpath, output_path, video_label, provider,
        )

        # Update progress
        entry["status"] = "done" if result["success"] else "failed"
        entry["provider"] = provider
        entry["api_calls"] = result.get("api_calls", 0)
        entry["failed_stage"] = result.get("failed_stage")
        entry["processed"] = _now_iso()
        entry["output"] = str(output_path.name)
        progress["videos"][stem] = entry

        # Update daily quota
        daily = progress["quota"].setdefault(today, {"gemini_calls": 0, "qwen_calls": 0})
        if provider == "gemini":
            daily["gemini_calls"] += result.get("api_calls", 0)
        else:
            daily["qwen_calls"] += result.get("api_calls", 0)

        progress["last_run"] = _now_iso()
        save_batch_progress(progress)

        if result["success"]:
            success_count += 1
        processed += 1

        # Status after each video
        gemini_today = daily["gemini_calls"]
        qwen_today = daily["qwen_calls"]
        print(f"\n  进度: {i}/{len(pending)}  "
              f"成功: {success_count}  "
              f"今日 Gemini: {gemini_today}/{args.daily_limit_gemini}  "
              f"Qwen: {qwen_today}")

    # Final summary
    print("\n" + "=" * 56)
    print(f"  本轮处理完成: {processed} 个视频, 成功 {success_count}")
    print(f"  今日 Gemini: {daily.get('gemini_calls', 0)}/{args.daily_limit_gemini}  "
          f"Qwen: {daily.get('qwen_calls', 0)}")
    print("=" * 56)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="批量处理外部目录的 MP4 视频 → NotebookLM Markdown",
    )
    parser.add_argument(
        "--source-dir", default=str(DEFAULT_SOURCE_DIR),
        help=f"视频源目录 (默认: {DEFAULT_SOURCE_DIR})",
    )
    parser.add_argument(
        "--output-dir", default=str(DEFAULT_OUTPUT_DIR),
        help=f"输出目录 (默认: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--duration-threshold", type=int, default=DEFAULT_DURATION_THRESHOLD_S,
        help=f"Gemini/Qwen 分界秒数 (默认: {DEFAULT_DURATION_THRESHOLD_S})",
    )
    parser.add_argument(
        "--daily-limit-gemini", type=int, default=DEFAULT_DAILY_LIMIT_GEMINI,
        help=f"Gemini 每日调用上限 (默认: {DEFAULT_DAILY_LIMIT_GEMINI})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="预览模式：探测时长 + 路由分析，不调用 API",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="仅显示当前批处理进度",
    )
    parser.add_argument(
        "--max-videos", type=int, default=0,
        help="限制本轮处理视频数量（用于测试）",
    )
    parser.add_argument(
        "--retry-failed", action="store_true",
        help="重试之前标记为失败的视频",
    )

    args = parser.parse_args()

    if args.dry_run:
        dry_run(Path(args.source_dir), args.duration_threshold, args.daily_limit_gemini)
    else:
        process_batch(args)


if __name__ == "__main__":
    main()
