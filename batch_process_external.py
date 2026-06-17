r"""Batch process MP4 videos from an external directory through the
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

# ── Config ──────────────────────────────────────────────────

DEFAULT_SOURCE_DIR = Path(r"E:\AI产品经理课")
DEFAULT_OUTPUT_DIR = MARKDOWNS_DIR / "batch"
BATCH_PROGRESS_FILE = Path(__file__).parent / ".progress_batch.json"

DEFAULT_DURATION_THRESHOLD_S = 9000       # 2.5h — Gemini ≤ this, Qwen >
# 免费层每个 flash 模型真实 RPD≈20(AI Studio 实测 2026-06-17)，留 2 防 429。
# 注意：此为 PER-MODEL 日上限，不是全部 Gemini 调用的总上限。
DEFAULT_DAILY_LIMIT_GEMINI = 18
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
# 免费层多 flash 模型轮询池（质量降序）。每个模型有独立 RPD，轮询=免费扩容。
# 规则：显式设了 GEMINI_MODEL_POOL → 用它；否则显式设了单个 GEMINI_MODEL
# （如 WIN 止血 set GEMINI_MODEL=gemini-2.5-flash-lite）→ 池只含该模型；都没设 → 默认池。
if "GEMINI_MODEL_POOL" in os.environ:
    GEMINI_MODEL_POOL = [m.strip() for m in os.environ["GEMINI_MODEL_POOL"].split(",") if m.strip()]
    if not GEMINI_MODEL_POOL:
        raise SystemExit("错误: GEMINI_MODEL_POOL 已设置但为空；请取消该环境变量或提供逗号分隔的模型名。")
elif os.environ.get("GEMINI_MODEL"):
    GEMINI_MODEL_POOL = [GEMINI_MODEL]   # 显式单模型（含 WIN 止血）：只用它
else:
    # 默认池仅含已确认可用的 model code（在用 / 官方确认）。
    # gemini-3-flash 官方 id 为 gemini-3-flash-preview（preview，限制更严、RPD 未确认），
    # 真实 smoke test 通过前不纳入默认池。
    GEMINI_MODEL_POOL = ["gemini-3.5-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite"]
GEMINI_BATCH_MAX_RETRIES = 2
GEMINI_BATCH_MAX_CONTINUATIONS = 2
QWEN_MODEL = os.environ.get("QWEN_MODEL", "qwen3.7-plus")
# Per-video frame guard for the Gemini path. Keyframes are 320px-wide JPEGs
# (~258 input tokens each), so a single Gemini call stays under the 250k
# free-tier TPM up to ~700 frames (~180k img tokens + transcript). Normal
# 1–2.5h videos fall under this and run as ONE Gemini call; videos above it
# are rerouted to Qwen's sliding-window path (process_single_video Phase 3),
# never windowed inside Gemini. NOT a 1M-context cap — 250k TPM is the
# binding free-tier limit. See CLAUDE.md Gemini limits.
GEMINI_MAX_FRAMES = 700
QWEN_MAX_FRAMES = 250
MAX_AUDIT_PROBES = 20   # hard cap on binary-search probe calls per window
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


# Lightweight probe prompt for binary audit search — intentionally minimal to
# keep token cost low. We just need to know if the frame set triggers inspection.
_AUDIT_PROBE_PROMPT = (
    "请确认：以下图片是否均为教育培训类内容截图？仅回答是或否，不需要其他解释。"
)

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
    """Remove characters unsafe for file path segments, preserve slash as dir separator."""
    return "".join(c for c in stem if c not in r'<>:"\|?*')


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
    """Scan source_dir recursively for media files, return {stem: path} sorted by stem.

    The stem is the relative path from source_dir without the file extension,
    using forward slashes (e.g. 'subdir/001_Lecture'). This matches the keys
    in .progress_batch.json so progress survives across runs.
    """
    videos: dict[str, Path] = {}
    for ext in VIDEO_EXTENSIONS:
        for p in sorted(source_dir.rglob(f"*{ext}")):
            rel = p.relative_to(source_dir)
            stem = str(rel.with_suffix('')).replace('\\', '/')
            videos[stem] = p
    return dict(sorted(videos.items()))


def route_provider(duration_s: float, threshold_s: int) -> str:
    """Return 'gemini' or 'qwen' based on duration."""
    return "gemini" if duration_s <= threshold_s else "qwen"


def _available_gemini_models(daily: dict, per_model_limit: int, expected_calls: int) -> list[str]:
    """Return Gemini models whose per-model quota can cover one conservative attempt."""
    by_model = daily.setdefault("gemini_calls_by_model", {})
    # legacy 迁移：旧进度只有总数 gemini_calls、无分模型计数时，把它归到历史单模型
    # （GEMINI_MODEL，默认 gemini-3.5-flash），避免把今天已打爆的模型当作 0 重新选中。
    if not by_model and daily.get("gemini_calls", 0) > 0:
        by_model[GEMINI_MODEL] = daily["gemini_calls"]
    return [
        model for model in GEMINI_MODEL_POOL
        if by_model.get(model, 0) + expected_calls <= per_model_limit
    ]


def _pick_gemini_model(daily: dict, per_model_limit: int, expected_calls: int = 1) -> str | None:
    """从 GEMINI_MODEL_POOL 选当天剩余额度够本次预计调用的最高质量 flash 模型。

    每个模型免费 RPD 独立计数（daily['gemini_calls_by_model']）。选择时预留
    expected_calls 额度，确保本次跑完不越过 per_model_limit。全部打满返回 None。
    """
    models = _available_gemini_models(daily, per_model_limit, expected_calls)
    return models[0] if models else None


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
    """Atomic write batch progress. Backs up previous file first."""
    if BATCH_PROGRESS_FILE.exists():
        backup = BATCH_PROGRESS_FILE.with_suffix(".json.bak")
        try:
            backup.write_bytes(BATCH_PROGRESS_FILE.read_bytes())
        except OSError:
            pass  # Non-critical: backup failure shouldn't block save
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


# ── Safety: Source-Progress Key Validation ──────────────────

def _validate_source_progress_match(
    videos: dict, progress: dict, source_dir: Path
) -> tuple[int, int, list]:
    """Check that discovered video stems match progress entries.

    Returns (matched, total_existing, mismatched_stems).
    If >50% of existing progress entries don't match discovered stems,
    the source_dir is probably wrong (subdirectory vs parent).
    """
    progress_videos = progress.get("videos", {})
    if not progress_videos:
        return 0, 0, []  # Fresh progress, no mismatch possible

    discovered_stems = set(videos.keys())
    progress_stems = set(progress_videos.keys())

    matched = discovered_stems & progress_stems
    only_in_progress = progress_stems - discovered_stems
    only_discovered = discovered_stems - progress_stems

    # If there are progress entries but NONE match, it's a clear mismatch
    if progress_stems and not matched:
        return 0, len(progress_stems), list(only_discovered)[:5]

    # If >50% of progress entries don't match discovered stems,
    # the source_dir might have changed
    mismatch_rate = len(only_in_progress) / max(len(progress_stems), 1)
    if mismatch_rate > 0.5:
        return len(matched), len(progress_stems), list(only_discovered)[:5]

    return len(matched), len(progress_stems), []


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
    from google.genai import types

    parts = [prompt, transcript_text]
    for fp in kept_frames:
        parts.append(frame_marker(fp, events))
        parts.append(types.Part(
            inline_data=types.Blob(mime_type="image/jpeg", data=fp.read_bytes())
        ))
    return parts

def _process_gemini(gemini_client, parts: list, video_label: str, models=None) -> dict:
    """Gemini synthesis path with model fallback.

    Returns {text, api_calls, success, failed_stage, gemini_calls_by_model}.
    call_gemini does not expose exact request count on failure, so each attempted
    model is charged conservatively as 1 + max_continuations.
    """
    if models is None:
        model_list = [GEMINI_MODEL]
    elif isinstance(models, str):
        model_list = [models]
    else:
        model_list = list(models)

    if not model_list:
        return {
            "text": None, "api_calls": 0, "success": False,
            "failed_stage": "gemini_no_model", "gemini_calls_by_model": {},
        }

    conservative_calls = 1 + GEMINI_BATCH_MAX_CONTINUATIONS
    calls_by_model: dict[str, int] = {}
    failed_models: list[str] = []
    for idx, model in enumerate(model_list, 1):
        if idx > 1:
            print(f"  [Gemini fallback] 改用下一个模型: {model}")
        text = call_gemini(
            gemini_client, parts,
            label=f"Gemini[{model}] {video_label[:20]}",
            model=model,
            thinking_budget=8192,
            max_retries=GEMINI_BATCH_MAX_RETRIES,
            max_continuations=GEMINI_BATCH_MAX_CONTINUATIONS,
        )
        calls_by_model[model] = calls_by_model.get(model, 0) + conservative_calls
        if text:
            return {
                "text": text,
                "api_calls": sum(calls_by_model.values()),
                "success": True,
                "failed_stage": None,
                "gemini_model": model,
                "failed_gemini_models": failed_models,
                "gemini_calls_by_model": calls_by_model,
            }
        failed_models.append(model)

    return {
        "text": None,
        "api_calls": sum(calls_by_model.values()),
        "success": False,
        "failed_stage": "gemini",
        "failed_gemini_models": failed_models,
        "gemini_calls_by_model": calls_by_model,
    }


def _find_clean_frames_binary(
    qwen_client, frames: list, events: list, label: str,
    _counter: list | None = None,
) -> tuple[list, int]:
    """Binary search to isolate frames that trigger Qwen content inspection.

    Uses a lightweight probe (not synthesis) to minimize token cost.
    Returns (clean_frames, probe_api_calls).
    Only called after a window already failed with data_inspection_failed.

    _counter is a one-element list [n] shared across all recursive calls to
    enforce MAX_AUDIT_PROBES; callers should not pass it.
    """
    from google.genai import types

    if _counter is None:
        _counter = [0]

    if not frames:
        return [], 0

    # Hard cap: if we've already used MAX_AUDIT_PROBES probes for this window,
    # stop recursing and drop the remaining frames conservatively.
    if _counter[0] >= MAX_AUDIT_PROBES:
        print(f"  [二分] 探针上限 {MAX_AUDIT_PROBES} 已达，剩余 {len(frames)} 帧保守丢弃")
        return [], 0

    # Build probe parts (no transcript — cheapest possible call)
    probe_parts = [_AUDIT_PROBE_PROMPT]
    for fp in frames:
        probe_parts.append(frame_marker(fp, events))
        probe_parts.append(types.Part(
            inline_data=types.Blob(mime_type="image/jpeg", data=fp.read_bytes())
        ))

    _counter[0] += 1
    result = call_qwen(
        qwen_client, probe_parts, label=f"{label}-probe",
        model=QWEN_MODEL, enable_thinking=False,
        max_retries=1, max_tokens=20,
    )
    probe_calls = result.get("api_calls", 1)

    if result.get("text") is not None:
        # All frames in this set passed — they're clean
        return frames, probe_calls

    if result.get("error") != "data_inspection_failed":
        # Non-audit failure on probe — can't recover, drop the set
        print(f"  [二分] {label}: 探针返回非审核错误，跳过 {len(frames)} 帧")
        return [], probe_calls

    if len(frames) == 1:
        # Isolated the single bad frame
        print(f"  [二分] 定位坏帧: {frames[0].name}", flush=True)
        return [], probe_calls

    # Split and recurse, sharing the same counter
    mid = len(frames) // 2
    left_clean, left_calls = _find_clean_frames_binary(
        qwen_client, frames[:mid], events, f"{label}-L", _counter
    )
    right_clean, right_calls = _find_clean_frames_binary(
        qwen_client, frames[mid:], events, f"{label}-R", _counter
    )
    return left_clean + right_clean, probe_calls + left_calls + right_calls


def _process_qwen(qwen_client, parts: list, video_label: str,
                  transcript_text: str, kept_frames: list, events: list) -> dict:
    """Qwen sliding-window synthesis path. Returns {text, api_calls, success, ...}."""
    from google.genai import types

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
        min_windows = (total_frames + QWEN_MAX_FRAMES - 1) // QWEN_MAX_FRAMES
        window_size = (total_frames + min_windows - 1) // min_windows
        overlap = max(0, min(int(window_size * 0.10), window_size // 3))

        windows = []
        start_idx = 0
        while start_idx < total_frames:
            end_idx = min(total_frames, start_idx + window_size)
            window_fps = sorted_frames[start_idx:end_idx]
            window_fps.sort(key=lambda fp: (
                int(frame_marker(fp, events).split("[")[1].split("]")[0].replace(":", ""))
                if "[" in frame_marker(fp, events) else 0
            ))
            windows.append(window_fps)
            if end_idx >= total_frames:
                break
            next_start = end_idx - overlap
            start_idx = next_start if next_start > start_idx else end_idx

        print(f"  分窗策略: {total_frames} 帧 → {len(windows)} 个窗口")
    else:
        windows = [kept_frames]
        print(f"  帧数 {total_frames} ≤ {QWEN_MAX_FRAMES}，无需分窗")

    # Window-level synthesis
    window_notes = []
    window_success = []
    failed_windows = []   # 1-based indices of windows that couldn't be recovered
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
        qwen_calls += int(w_result.get("api_calls", 1) if isinstance(w_result, dict) else 1)
        w_text = w_result.get("text") if isinstance(w_result, dict) else None
        w_ok = bool(w_text)

        # Audit block: binary search to isolate bad frames, then re-synthesize
        if not w_ok and w_result.get("error") == "data_inspection_failed":
            print(f"  [{wlabel}] ⚠ 审核阻断，启动二分隔离 ({len(wf)} 帧)...")
            clean_frames, probe_calls = _find_clean_frames_binary(
                qwen_client, wf, events, wlabel
            )
            qwen_calls += probe_calls
            dropped = len(wf) - len(clean_frames)
            print(f"  [{wlabel}] 二分完成: 保留 {len(clean_frames)} 帧，丢弃 {dropped} 坏帧")

            if clean_frames:
                # Re-synthesize with clean frames only
                clean_parts = [w_prompt, transcript_text]
                for fp in clean_frames:
                    clean_parts.append(frame_marker(fp, events))
                    clean_parts.append(types.Part(
                        inline_data=types.Blob(mime_type="image/jpeg", data=fp.read_bytes())
                    ))
                retry_result = call_qwen(
                    qwen_client, clean_parts,
                    label=f"{wlabel}-clean", model=QWEN_MODEL,
                    enable_thinking=True, thinking_budget=4096,
                    max_tokens=48000, max_retries=2,
                )
                qwen_calls += int(retry_result.get("api_calls", 1))
                w_text = retry_result.get("text")
                w_ok = bool(w_text)

        window_success.append(w_ok)
        if w_ok:
            window_notes.append(w_text)
            print(f"  [{wlabel}] ✓ {len(w_text):,} 字符")
        else:
            failed_windows.append(wi + 1)
            print(f"  [{wlabel}] ✗ 最终失败，跳过此窗口继续")

    if not any(window_success):
        return {"text": None, "api_calls": qwen_calls, "success": False, "failed_stage": "qwen-windows"}
    if failed_windows:
        print(f"  [警告] 窗口 {failed_windows} 最终失败，用 {len(window_notes)}/{window_count} 个成功窗口继续组装")

    if window_count == 1:
        qwen_text = window_notes[0]
    else:
        # Final assembly
        print(f"\n  [Qwen-Assembly] 合并 {window_count} 个窗口笔记...")
        _asm_facts = extract_qwen_critical_facts(window_notes)
        _asm_blocks = extract_qwen_narrative_blocks(window_notes)
        if failed_windows:
            _success_indices = [i for i in range(1, window_count + 1) if i not in failed_windows]
            _constraint = (
                f"约束：视频共 {window_count} 个窗口，成功窗口：{_success_indices}，"
                f"缺失窗口：{failed_windows}（审核拦截，无资料）。"
                f"仅按成功窗口生成正文，最终章节数必须 ≥ {len(window_notes)}。禁止为缺失窗口补全内容。\n\n"
            )
        else:
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
        qwen_calls += int(assembly_result.get("api_calls", 1) if isinstance(assembly_result, dict) else 1)
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

    # Prepend a visible warning block when some windows were dropped
    if failed_windows and qwen_text:
        total_w = window_count
        warning_block = (
            f"> **⚠ 内容不完整警告**：本视频共 {total_w} 个处理窗口，"
            f"窗口 {failed_windows} 因 Qwen 内容审核或探针上限最终失败，"
            f"对应时间段的视觉证据已缺失。建议用 `--retry-failed` 重跑或人工补充。\n\n"
        )
        qwen_text = warning_block + qwen_text

    return {
        "text": qwen_text,
        "api_calls": qwen_calls,
        "success": True,
        "failed_stage": None,
        "partial_windows": failed_windows if failed_windows else None,
    }


def process_single_video(
    gemini_client,
    qwen_client,
    video_path: Path,
    output_path: Path,
    video_label: str,
    provider: str,
    gemini_model: str = GEMINI_MODEL,
    gemini_models: list[str] | None = None,
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
        result["frame_count"] = len(kept_frames)
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
        if provider == "gemini" and len(kept_frames) > GEMINI_MAX_FRAMES:
            # 帧数护栏：单次 Gemini 调用会超 250k 免费层 TPM，改交 Qwen 成熟的分窗处理。
            # 罕见路径（≤2.5h 且 >GEMINI_MAX_FRAMES 帧的高密度视频），正常路由基本不触发。
            if qwen_client is None:
                print(f"  ⚠ 帧数 {len(kept_frames)} > {GEMINI_MAX_FRAMES} 护栏，但无 Qwen client，无法 reroute，放弃")
                synth_result = {"text": None, "api_calls": 0,
                                "success": False, "failed_stage": "gemini_frames_over_guard"}
            else:
                print(f"  帧数 {len(kept_frames)} > {GEMINI_MAX_FRAMES} 护栏 → 改用 Qwen 处理（避免单次 Gemini 调用超 250k TPM）")
                synth_result = _process_qwen(
                    qwen_client, parts, video_label,
                    transcript_text, kept_frames, events,
                )
                result["provider"] = "qwen"  # 实际由 Qwen 承载，供配额按 Qwen 计费/记录
        elif provider == "gemini":
            synth_result = _process_gemini(
                gemini_client, parts, video_label,
                gemini_models or [gemini_model],
            )
        else:
            synth_result = _process_qwen(
                qwen_client, parts, video_label,
                transcript_text, kept_frames, events,
            )

        result["api_calls"] = synth_result["api_calls"]
        result["success"] = synth_result["success"]
        result["failed_stage"] = synth_result["failed_stage"]
        result["partial_windows"] = synth_result.get("partial_windows")
        result["gemini_model"] = synth_result.get("gemini_model")
        result["failed_gemini_models"] = synth_result.get("failed_gemini_models")
        result["gemini_calls_by_model"] = synth_result.get("gemini_calls_by_model")

        # Phase 4: Write output
        if synth_result["text"]:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(f"# {video_path.stem}\n\n")
                f.write(synth_result["text"].rstrip())
                f.write(_transcript_appendix(transcript_text))
            print(f"  ✓ 输出: {output_path.name} ({len(synth_result['text']):,} 字符)")
        else:
            actual_provider = result.get("provider", provider)  # reroute 后为 qwen
            print(f"  ✗ {actual_provider.upper()} 合成失败")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                f"# {video_path.stem}\n\n> {actual_provider.upper()} 合成失败\n\n"
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
    _pool_cap = len(GEMINI_MODEL_POOL) * daily_limit_gemini
    print(f"  Gemini 模型池: {len(GEMINI_MODEL_POOL)} 个 × {daily_limit_gemini}/模型 = {_pool_cap} 次/天")
    print(f"    {', '.join(GEMINI_MODEL_POOL)}")
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
    gemini_days = "∞" if _pool_cap <= 0 and gemini_count else max(1, gemini_est // max(_pool_cap, 1) + 1)
    print(f"  Gemini 视频: {gemini_count}  预估调用: {gemini_est}  预估天数: {gemini_days}")
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

    # ── Safety: validate source_dir matches progress keys ──
    if not args.force:
        matched, total_existing, mismatched = _validate_source_progress_match(
            videos, progress, source_dir
        )
        if total_existing > 0 and matched == 0:
            print("=" * 70)
            print("⛔ 安全防护：进度文件 Key 完全不匹配！")
            print("=" * 70)
            print(f"  源目录:     {source_dir}")
            print(f"  发现的 stem 示例:")
            for s in mismatched[:3]:
                print(f"    • {s}")
            print(f"  进度文件中有 {total_existing} 个条目，但无一匹配。")
            print()
            print("  可能原因：")
            print(f"  1. source_dir 用了子目录，而进度 key 基于父目录")
            print(f"     例如：--source-dir \"{source_dir.parent}\" 而非 \"{source_dir}\"")
            print(f"  2. source_dir 完全不正确")
            print()
            print("  操作建议：")
            print(f"  1. 先 --dry-run 查看生成的 stem 列表")
            print(f"  2. 从进度文件随机取一个 key 对比格式")
            print(f"  3. 确认后用 --force 跳过此检查（不推荐）")
            print("=" * 70)
            sys.exit(1)
        elif total_existing > 10 and len(mismatched) > 0:
            mismatch_pct = (total_existing - matched) / total_existing * 100
            print("=" * 70)
            print(f"⛔ 安全防护：{mismatch_pct:.0f}% 的进度条目与当前 source_dir 不匹配，中止。")
            print("=" * 70)
            print(f"  发现: {len(videos)} stems, 匹配: {matched}, 进度总数: {total_existing}")
            print(f"  source_dir: {source_dir}")
            print(f"  如确认 source_dir 正确，使用 --force 跳过此检查")
            print("=" * 70)
            sys.exit(1)

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
        if status in ("failed", "partial") and not args.retry_failed:
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

    # Per-run call budget enforcement
    run_call_budget = args.max_calls_per_run
    run_calls_used = 0
    if run_call_budget > 0:
        # Estimate total calls for the run, accounting for auto-reroute and the
        # >GEMINI_MAX_FRAMES guard that reroutes oversized Gemini videos to Qwen.
        _cpw = 1 + GEMINI_BATCH_MAX_CONTINUATIONS  # conservative calls per Gemini call

        def _est_calls_for(e: dict, will_reroute: bool) -> int:
            fc = e.get("frame_count", 0)
            # 实际由 Qwen 承载：原生 Qwen / >2.5h reroute / gemini 超帧护栏 → 都走 Qwen 分窗
            on_qwen = (
                will_reroute
                or (e.get("provider") or "gemini") == "qwen"
                or fc > GEMINI_MAX_FRAMES
            )
            if on_qwen:
                # Qwen 分窗：ceil(fc/QWEN_MAX_FRAMES) 窗，多窗再加 1 次 assembly，每步保守 _cpw
                n_windows = (fc + QWEN_MAX_FRAMES - 1) // QWEN_MAX_FRAMES if fc > 0 else 1
                return _cpw if n_windows <= 1 else (n_windows + 1) * _cpw
            return _cpw  # 单次 Gemini

        est_total = 0
        for s in pending:
            _e = progress["videos"].get(s, {})
            _will_reroute = (
                args.retry_failed
                and _e.get("failed_stage") == "gemini"
                and _e.get("duration_s", 0) > args.duration_threshold
            )
            est_total += _est_calls_for(_e, _will_reroute)
        print(f"预估本轮 API 调用: ~{est_total}  (单次上限: {run_call_budget})")
        if est_total > run_call_budget:
            print(f"⛔ 预估调用数 {est_total} 超过单次上限 {run_call_budget}，中止。")
            print(f"   使用 --max-calls-per-run {est_total + 10} 或 --max-calls-per-run 0 解除限制。")
            sys.exit(1)

    # Daily quota check（Gemini 为 per-model RPD，不能再用总 gemini_calls 对单模型上限判断）
    today = date.today().isoformat()
    daily = progress["quota"].setdefault(today, {"gemini_calls": 0, "qwen_calls": 0})
    gemini_expected_calls = 1 + GEMINI_BATCH_MAX_CONTINUATIONS
    gemini_available_today = _available_gemini_models(
        daily, args.daily_limit_gemini, expected_calls=gemini_expected_calls,
    )
    gemini_pool_cap = len(GEMINI_MODEL_POOL) * args.daily_limit_gemini
    print(f"今日 Gemini 池配额: {daily.get('gemini_calls', 0)}/{gemini_pool_cap} 已用")
    print(f"  可承载本次 Gemini 尝试的模型: {gemini_available_today or '无'}")

    if not gemini_available_today:
        # Check if any pending videos are Gemini-routed
        gemini_pending = sum(
            1 for s in pending
            if progress["videos"].get(s, {}).get("provider") == "gemini"
        )
        if gemini_pending > 0:
            print(f"⚠ 今日 Gemini 模型池可用配额不足，将跳过 {gemini_pending} 个 Gemini 视频")

    # Initialize API clients
    print("\n初始化 API 客户端...")
    gemini_api_key = os.environ.get("OPENCLAW_GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    qwen_api_key = os.environ.get("DASHSCOPE_API_KEY")

    gemini_client = None
    if gemini_api_key:
        try:
            from google import genai
            from google.genai import types

            http_opts = types.HttpOptions(
                timeout=3600000,
                base_url=os.environ.get("GEMINI_BASE_URL") or None,
                api_version=os.environ.get("GEMINI_API_VERSION", "v1beta") if os.environ.get("GEMINI_BASE_URL") else None,
            )
            gemini_client = genai.Client(api_key=gemini_api_key, http_options=http_opts)
            print(f"  Gemini: ✓ 模型池 {GEMINI_MODEL_POOL}（每模型 RPD 上限见 --daily-limit-gemini）")
        except ImportError as exc:
            print(f"  Gemini: ✗ 缺少依赖 {exc.name} — Gemini 视频将被跳过")
    else:
        print("  Gemini: ✗ 无 API Key — Gemini 视频将被跳过")

    qwen_client = None
    if qwen_api_key:
        try:
            from google.genai import types as _qwen_part_types  # noqa: F401
            from openai import OpenAI

            qwen_client = OpenAI(api_key=qwen_api_key, base_url=DASHSCOPE_BASE_URL)
            print(f"  Qwen: ✓ ({QWEN_MODEL})")
        except ImportError as exc:
            print(f"  Qwen: ✗ 缺少依赖 {exc.name} — Qwen 视频将被跳过")
    else:
        print("  Qwen: ✗ 无 API Key — Qwen 视频将被跳过")

    # Process loop
    processed = 0
    success_count = 0
    for i, (stem, vpath) in enumerate(pending.items(), 1):
        entry = progress["videos"].get(stem, {})
        provider = entry.get("provider", "gemini")

        # Auto-reroute: if retrying a Gemini failure on a long video, switch to Qwen
        if (args.retry_failed
                and entry.get("failed_stage") == "gemini"
                and entry.get("duration_s", 0) > args.duration_threshold):
            provider = "qwen"
            print(f"  [路由修正] {stem[:40]}: failed_stage=gemini + 时长超阈值 → 改用 Qwen")

        # 帧数护栏预判：已知帧数 > GEMINI_MAX_FRAMES 的 Gemini 视频会 reroute 到 Qwen，
        # 闸门提前按 Qwen 处理，避免被 Gemini 日配额闸门误拦。
        # 首次处理无 frame_count（默认 0）时无法预判，仍按 Gemini 保守处理（预处理后由 Phase 3 内部 reroute 兜底）。
        if provider == "gemini" and entry.get("frame_count", 0) > GEMINI_MAX_FRAMES:
            provider = "qwen"
            print(f"  [护栏预判] {stem[:40]}: 已知 {entry.get('frame_count')} 帧 > {GEMINI_MAX_FRAMES} → 闸门按 Qwen")

        # Quota gate for Gemini —— 多模型轮询：选当天还有余额的最高质量 flash 模型
        chosen_gemini_model = None
        gemini_model_candidates: list[str] = []
        if provider == "gemini":
            if gemini_client is None:
                print(f"\n⏸  [{i}/{len(pending)}] {stem[:50]} — 无 Gemini API Key，跳过")
                continue
            daily = progress["quota"].setdefault(today, {"gemini_calls": 0, "qwen_calls": 0})
            quota_model_candidates = _available_gemini_models(
                daily, args.daily_limit_gemini, expected_calls=gemini_expected_calls,
            )
            gemini_model_candidates = quota_model_candidates
            if run_call_budget > 0:
                remaining_budget = run_call_budget - run_calls_used
                max_attempt_models = max(0, remaining_budget // gemini_expected_calls)
                gemini_model_candidates = gemini_model_candidates[:max_attempt_models]
            chosen_gemini_model = gemini_model_candidates[0] if gemini_model_candidates else None
            if not gemini_model_candidates:
                if quota_model_candidates:
                    print(f"\n⛔ [{i}/{len(pending)}] {stem[:50]} — 本轮剩余调用预算不足 "
                          f"({run_call_budget - run_calls_used}/{gemini_expected_calls})，中止")
                    break
                cap = len(GEMINI_MODEL_POOL) * args.daily_limit_gemini
                print(f"\n⏸  [{i}/{len(pending)}] {stem[:50]} — 所有 Gemini 模型今日配额已满 "
                      f"({len(GEMINI_MODEL_POOL)}×{args.daily_limit_gemini}={cap})，跳过")
                continue

        if provider == "qwen" and qwen_client is None:
            print(f"\n⏸  [{i}/{len(pending)}] {stem[:50]} — 无 Qwen API Key，跳过")
            continue

        video_label = f"{i}/{len(pending)} {stem[:30]}"
        output_path = output_dir / f"{_safe_name(stem)}.md"

        result = process_single_video(
            gemini_client, qwen_client, vpath, output_path, video_label, provider,
            gemini_model=chosen_gemini_model or GEMINI_MODEL,
            gemini_models=gemini_model_candidates or None,
        )

        # Update progress
        partial = result.get("partial_windows")
        if not result["success"]:
            entry["status"] = "failed"
        elif partial and not args.allow_partial:
            entry["status"] = "partial"
            entry["partial_windows"] = partial
            print(f"  ⚠ 标记为 partial（窗口 {partial} 缺失）。用 --allow-partial 改标 done，或 --retry-failed 重跑。")
        else:
            entry["status"] = "done"
            entry.pop("partial_windows", None)
        # 帧数护栏可能把 gemini 视频实际交给 Qwen；按实际承载 provider 计费/记录
        billed_provider = result.get("provider", provider)
        entry["provider"] = billed_provider
        entry["api_calls"] = result.get("api_calls", 0)
        entry["failed_stage"] = result.get("failed_stage")
        entry["processed"] = _now_iso()
        if result.get("frame_count"):
            entry["frame_count"] = result["frame_count"]
        if result.get("gemini_model"):
            entry["gemini_model"] = result["gemini_model"]
        if result.get("failed_gemini_models"):
            entry["failed_gemini_models"] = result["failed_gemini_models"]
        if result.get("gemini_calls_by_model"):
            entry["gemini_calls_by_model"] = result["gemini_calls_by_model"]
        entry["output"] = str(output_path.name)
        progress["videos"][stem] = entry

        # Update daily quota（Gemini 按选中模型分别计数，每模型独立 RPD）
        daily = progress["quota"].setdefault(today, {"gemini_calls": 0, "qwen_calls": 0})
        _calls = result.get("api_calls", 0)
        if billed_provider == "gemini":
            daily["gemini_calls"] += _calls
            _model_calls = result.get("gemini_calls_by_model") or {}
            if _model_calls:
                _bm = daily.setdefault("gemini_calls_by_model", {})
                for _model, _model_call_count in _model_calls.items():
                    _bm[_model] = _bm.get(_model, 0) + int(_model_call_count)
            elif chosen_gemini_model:
                _bm = daily.setdefault("gemini_calls_by_model", {})
                _bm[chosen_gemini_model] = _bm.get(chosen_gemini_model, 0) + _calls
        else:
            daily["qwen_calls"] += _calls

        # Enforce per-run call budget —— 先存盘+计数+打印，再决定是否停止，
        # 避免已烧的调用因 break 跳过 save_batch_progress 而下次重跑重复烧 API。
        should_stop = False
        if run_call_budget > 0:
            run_calls_used += result.get("api_calls", 0)
            should_stop = run_calls_used >= run_call_budget

        progress["last_run"] = _now_iso()
        save_batch_progress(progress)

        if result["success"]:
            success_count += 1
        processed += 1

        # Status after each video（按模型显示 Gemini 用量，每模型独立 RPD）
        _by_model = daily.get("gemini_calls_by_model", {})
        _gem_sum = " ".join(
            f"{m.replace('gemini-', '')}:{_by_model.get(m, 0)}/{args.daily_limit_gemini}"
            for m in GEMINI_MODEL_POOL
        )
        print(f"\n  进度: {i}/{len(pending)}  成功: {success_count}")
        print(f"  今日 Gemini[{_gem_sum}]  Qwen: {daily['qwen_calls']}")

        if should_stop:
            print(f"\n⛔ 本轮 API 调用已达上限 {run_call_budget}，中止。剩余 {len(pending)-i} 个视频待下次处理。")
            break

    # Final summary
    print("\n" + "=" * 56)
    print(f"  本轮处理完成: {processed} 个视频, 成功 {success_count}")
    print(f"  今日 Gemini: {daily.get('gemini_calls', 0)}/{len(GEMINI_MODEL_POOL) * args.daily_limit_gemini}(池容量)  "
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
        help=f"每个 Gemini 模型的每日 RPD 上限 (默认 {DEFAULT_DAILY_LIMIT_GEMINI}, PER-MODEL; 总日容量=模型池大小×此值)",
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
        help="重试之前标记为失败或 partial 的视频",
    )
    parser.add_argument(
        "--allow-partial", action="store_true",
        help="允许部分窗口失败的视频标记为 done（默认标 partial，需 --retry-failed 重跑）",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="跳过 source_dir 与进度 key 匹配校验（危险！仅在确认 source_dir 正确时使用）",
    )
    parser.add_argument(
        "--max-calls-per-run", type=int, default=100,
        help="单次运行最大 API 调用数上限，超过则中止（0=不限制，默认100）",
    )

    args = parser.parse_args()

    if args.dry_run:
        dry_run(Path(args.source_dir), args.duration_threshold, args.daily_limit_gemini)
    else:
        process_batch(args)


if __name__ == "__main__":
    main()
