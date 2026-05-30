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
import hashlib
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
QWEN_MODEL              = os.environ.get("QWEN_MODEL", "qwen3.6-plus")
GEMINI_IMAGE_HARD_LIMIT = 3000   # API ceiling; fallback priority sampling above this
QWEN_IMAGE_HARD_LIMIT   = 250
QWEN_DEFAULT_MAX_FRAMES = 128
QWEN_WINDOW_TARGET_FRAMES = 200
QWEN_WINDOW_OVERLAP_FRAMES = 20
QWEN_WINDOW_NOTE_VERSION = "qwen-window-note-v3"
QWEN_FINAL_ASSEMBLY_VERSION = "qwen-final-assembly-v2"
QWEN_CRITICAL_FACT_VERSION = "qwen-critical-facts-v2"
QWEN_NARRATIVE_BLOCK_VERSION = "qwen-narrative-blocks-v1"
MAX_RETRIES             = 2      # Gemini quota guard: keep automatic retries small
MAX_CONTINUATIONS       = 2      # Gemini quota guard: 1 initial + 2 continuation calls max
RETRY_DELAY             = 65

# ── P0 QC config ──────────────────────────────────────────────────────────────

GAP_THRESHOLD_S     = 30    # seconds above typical chunk interval → counts as a gap
SILENT_CHARS_LIMIT  = 10    # transcript chars below this → silent chunk
TAIL_COVERAGE_RATIO = 0.85  # transcript must reach ≥ 85% of estimated stream end
BODY_COVERAGE_GAP_S = 120   # warn if last Markdown chapter ends >2 min before stream end
QWEN_BODY_MIN_TRANSCRIPT_RATIO = 0.20
QWEN_FACT_RETENTION_MIN_RATIO = 0.90
QWEN_NARRATIVE_RETENTION_MIN_RATIO = 0.32
# Qwen one-shot → sliding-window auto-route threshold.
# Validated: 54K chars one-shot → overcompressed (BUG#109); 41K sliding-window → QC pass.
# Qwen output cap ~32K Chinese chars; transcripts above 30K chars exhaust output budget.
QWEN_AUTO_SLIDING_WINDOW_CHARS = 30_000
QWEN_NARRATIVE_MIN_BLOCKS_PER_WINDOW = 2
QWEN_CRITICAL_FACT_TERMS = [
    "75分",
    "所见即所得",
    "不要替换",
    "34岁",
    "2017年",
    "年终奖",
    "99.9%",
    "4万积分",
    "19.9万积分",
    "30万积分",
    "15秒",
    "30秒",
    "1分钟",
    "3分钟",
    "Remotion",
    "HyperFrames",
    "Coze",
    "扣子",
    "Context Compression",
    "即梦",
    "Dreamina",
    "FDE",
]

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

QWEN_NOTEBOOKLM_PROMPT_TEXT = """
# 角色与目标
你是一个面向 NotebookLM / 长文本 RAG 的中文直播知识库文档生成器。你的任务不是写高管摘要，也不是帮读者节省篇幅，而是把输入的完整逐字稿和关键帧截图转成一份**可检索、可追溯、细节保真的 Markdown 知识库源文档**。

# 最高优先级：禁止过度压缩
Qwen 容易把口语内容整理成短 bullet points。当前任务明确禁止这种做法。请保留讲师的原生语境、案例链路、具体数字、打分、提示词、屏幕文字和重要原话。宁可输出更长，也不要把长案例压缩成一句概括。

# 必须保留的高价值证据
- 讲师现场展示或口述的 Prompt / 提示词 / 配置 / 代码 / 命令 / UI 文案，必须原样或近原样保留，并用 Markdown 代码块包裹。
- 具体案例的因果链路必须完整保留：问题是什么、讲师怎么判断、改了什么、为什么这样改、效果如何。
- 具体数字、时间、评分、比例、工具名、人名和课程名不能省略。例如 75 分、99.9%、15 秒/30 秒、Remotion、HyperFrames、Coze、FDE 等。
- 对讲师原话、金句、判断标准，要尽量保留原始表达，不要改写成抽象口号。
- 视觉/屏幕内容不能只写"展示了截图"。要描述截图上出现的标题、表格、红字、圈注、代码、配置项或演示结果。

# 输入说明
- **逐字稿**: 带全局时间戳的中文直播转写。
- **关键帧**: 按时间排序的视频截图，包含幻灯片切换、画笔标注、代码/配置界面、群聊或产品演示画面。
- 当截图信息和逐字稿不一致或互补时，请把截图内容作为视觉证据写入正文。

# 必须输出的 Markdown 结构

必须从 H1 开始，不能省略标题：

# （给这场直播起一个准确、具体的中文标题）

## 1. 视频元数据
- **推测主题：**
- **核心关键词：** 5-12 个关键词，优先保留原始术语。
- **适用受众/场景：**

## 2. 核心知识字典（Glossary）
请提炼 5-8 个概念。定义要清晰，但不要牺牲细节。优先包含 FDE、AI播客生成、人物一致性、流量重组洗稿、安全底线、Remotion/HyperFrames/Coze 等实际出现的概念。

## 3. 详尽内容解析
请按真实时间线拆分章节。每个章节标题必须独立成行，并使用：

### [HH:MM:SS - HH:MM:SS] 章节标题

每个章节必须包含以下四项，不能缺项：
- **核心论点：** 本段结论。
- **详细展开：** 详尽保留讲师解释、案例背景、判断过程、操作步骤、数字、评分、因果关系。不要只列短 bullet。
- **视觉/屏幕内容：** 详细转写屏幕信息。若出现 Prompt、配置、代码、命令、UI 文案，请用代码块保留。
- **重要金句/原话：** 1-3 句原话或近原话。

## 4. 遗留问题与下一步行动
记录视频结尾、课程安排、项目报名建议、待办事项或未解决问题。

# 质量自检
输出前自检：
1. 是否有 H1 标题？
2. 是否保留了 Prompt/提示词/配置/代码块？
3. 是否保留了具体案例的细节、数字、评分和原话？
4. 是否每个时间线章节都有视觉/屏幕内容？
5. 是否避免了"高管摘要"式过度压缩？

如果不确定某个细节是否重要，保留它。NotebookLM 后续检索依赖这些细节。
"""

QWEN_WINDOW_NOTE_PROMPT_TEXT = """
# 角色与目标
你是 NotebookLM 知识库的"窗口级证据采集员"。我会提供长直播中的一个时间窗口：本窗口逐字稿 + 本窗口关键帧。你的任务是生成**保真窗口笔记**，不是最终文章，也不是摘要。

# 最高优先级
禁止高管摘要化，禁止把长案例压缩成一句话。请捕获本窗口中所有后续 RAG 检索可能需要的细节。

# 必须保留
- Prompt / 提示词 / 配置 / 代码 / 命令 / UI 文案：用 Markdown 代码块保存。
- 具体案例链路：问题、判断、修改、原因、效果。
- 具体数字和标签：评分、比例、时长、工具名、人名、项目名。
- 视觉证据：截图/幻灯片/群聊/产品界面上的标题、表格、红字、圈注、代码、配置项。
- 讲师原话或近原话：尤其是判断标准、金句、风险提示。

# 严厉指令：数字与时间句强制留存
看到任何包含具体数字、年份、年龄、百分比、时长（秒/分钟）、金额、积分、分数、比例的句子，必须原文或近原文保留。不要把“35岁转型”改成“中年转型”，不要把“15秒/30秒/1分钟/3分钟”改成“短时长”，不要把“60分/90分”改成“较低/较高评分”。这些句子后续会被程序抽取为 Critical Facts，缺失会导致最终 QC 失败。

# 输出格式
请严格使用以下结构：

## Window Metadata
- **时间范围：** [HH:MM:SS - HH:MM:SS]
- **窗口序号：**
- **覆盖帧数：**
- **是否包含重叠上下文：**

## Faithful Notes
按时间顺序记录本窗口信息。不要为了简洁而删除细节。

## Critical Number Sentences
逐条列出本窗口所有包含年份、年龄、百分比、时长、金额、积分、分数、比例的完整句子或近原文句子。没有则写"未发现"。

## Narrative Evidence Blocks
保留本窗口中 2-6 段最有 NotebookLM 检索价值的长叙事证据块。每段 300-800 字，尽量接近讲师原始表达，不要改成思维导图短句。优先保留：
- 个人经历、转行故事、职业判断、心理转折。
- 案例复盘中的完整因果链路和长文案示例。
- 商业判断、成本分析、踩坑故事、风险解释。
- 能体现"网感"、语气、原生语境的长段说明。

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

QWEN_FINAL_ASSEMBLY_PROMPT_TEXT = """
# 角色与目标
你是 NotebookLM / 长文本 RAG 知识库文档的最终组装器。你将收到：
1. 由程序从 Qwen 窗口笔记中确定性抽取出的 Critical Facts Checklist；
2. 由程序从 Qwen 窗口笔记中确定性抽取出的 Narrative Evidence Blocks；
3. 多个 Qwen 窗口级保真笔记。

这些输入是唯一权威来源。你的任务是在不调用其他模型、不依赖 Gemini 的前提下，组装成一份详尽、可检索、细节保真的 Markdown 文档。

# 关键规则
- 不能把窗口笔记压缩成高管摘要。
- 不能删除窗口笔记中保存的 Prompt、代码块、配置、UI 文案、案例打分、数字、金句和视觉证据。
- Critical Facts Checklist 中的每一项都必须出现在最终正文、技术资产附录或关键事实索引中。不能遗漏分数、年份、年龄、百分比、时长、金额、积分、工具名、Prompt 关键词。
- Narrative Evidence Blocks 是防止长文叙事被压缩的保底证据。最终正文必须吸收这些长段的细节和语气；不能只把它们改写成一句 bullet。
- 可以去重 overlap，但不能因为去重丢掉上下文。
- 章节必须按真实时间线线性展开，禁止出现大章节包住小章节的重叠时间段。
- 每个输入窗口必须对应至少一个独立章节，禁止将多个窗口内容合并为单一超大章节。最终章节数 ≥ 输入窗口数（见输入头部的约束行）。
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
集中列出 Critical Facts Checklist 中的关键数字、年份、年龄、百分比、时长、金额、积分、评分、工具名和 Prompt 关键词。每条要标明来源窗口，并保留上下文短句。这个索引用于 NotebookLM 精确检索，不要省略任何一条。

# 自检
输出前确认：H1 存在；所有窗口都有内容进入正文；章节数 ≥ 输入窗口数；Critical Facts Checklist 全部落地到正文/技术资产附录/关键事实索引；Narrative Evidence Blocks 已进入正文或叙事证据附录；Prompt/代码块没有丢；技术资产附录存在；关键事实索引存在；视觉证据没有被泛化成"展示了截图"；章节时间线不重叠；正文不是短摘要。

# 隐藏覆盖标记（必须输出）
在文档最后一行添加 HTML 注释，列出已纳入最终正文的窗口编号，格式必须严格为：
<!-- qwen_window_coverage: 1,2,3 -->
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


def _payload_timestamps_are_global(frames: list[dict], chunk_start_s: int) -> bool:
    if chunk_start_s <= 0 or not frames:
        return False
    timestamps = [
        float(f.get("timestamp_s", 0) or 0)
        for f in frames
        if isinstance(f.get("timestamp_s", 0), (int, float))
    ]
    if not timestamps:
        return False
    first_ts = min(timestamps)
    last_ts = max(timestamps)
    return first_ts >= max(0, chunk_start_s - 5) and last_ts >= chunk_start_s


def load_chunk_frames(payload_path: Path, chunk_start_s: int) -> list[dict]:
    """Load frames from a per-chunk payload.json, adjusting timestamps to global seconds."""
    if not payload_path.exists():
        return []
    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    payload_frames = payload.get("frames", [])
    timestamps_are_global = _payload_timestamps_are_global(payload_frames, chunk_start_s)
    result = []
    for f in payload_frames:
        local_ts  = f.get("timestamp_s", 0)
        global_ts = local_ts if timestamps_are_global else chunk_start_s + local_ts

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
            "timestamp_scope": "global" if timestamps_are_global else "local",
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

def _sample_evenly_indexed(indexed_frames: list[tuple[int, dict]], limit: int) -> list[tuple[int, dict]]:
    """Sample frames evenly while retaining the first and last item when possible."""
    if limit <= 0 or not indexed_frames:
        return []
    if len(indexed_frames) <= limit:
        return list(indexed_frames)
    if limit == 1:
        return [indexed_frames[len(indexed_frames) // 2]]

    max_index = len(indexed_frames) - 1
    selected_positions: list[int] = []
    seen: set[int] = set()
    for i in range(limit):
        pos = round(i * max_index / (limit - 1))
        if pos not in seen:
            selected_positions.append(pos)
            seen.add(pos)

    cursor = 0
    while len(selected_positions) < limit and cursor < len(indexed_frames):
        if cursor not in seen:
            selected_positions.append(cursor)
            seen.add(cursor)
        cursor += 1

    return [indexed_frames[pos] for pos in sorted(selected_positions[:limit])]


def select_frames(frames: list[dict], *, image_limit: int = GEMINI_IMAGE_HARD_LIMIT) -> list[dict]:
    """Return selected frames with balanced type quotas when over limit."""
    if image_limit <= 0:
        return []
    if len(frames) <= image_limit:
        return frames

    indexed_by_type = {"slide": [], "annotation": [], "context": []}
    for idx, frame in enumerate(frames):
        indexed_by_type[_frame_type(frame)].append((idx, frame))

    weights = {"slide": 0.55, "annotation": 0.25, "context": 0.20}
    priority = ["slide", "annotation", "context"]
    allocation = {key: 0 for key in priority}
    for key in priority:
        if indexed_by_type[key]:
            allocation[key] = max(1, int(image_limit * weights[key]))

    while sum(allocation.values()) > image_limit:
        reducible = [key for key in reversed(priority) if allocation[key] > 1]
        if reducible:
            allocation[reducible[0]] -= 1
        else:
            for key in reversed(priority):
                if allocation[key] > 0:
                    allocation[key] -= 1
                    break

    for key in priority:
        allocation[key] = min(allocation[key], len(indexed_by_type[key]))

    remaining = image_limit - sum(allocation.values())
    while remaining > 0:
        progressed = False
        for key in priority:
            if allocation[key] < len(indexed_by_type[key]):
                allocation[key] += 1
                remaining -= 1
                progressed = True
                if remaining == 0:
                    break
        if not progressed:
            break

    selected_indexed: list[tuple[int, dict]] = []
    for key in priority:
        selected_indexed.extend(_sample_evenly_indexed(indexed_by_type[key], allocation[key]))

    return [frame for _, frame in sorted(selected_indexed, key=lambda item: item[0])]


def build_gemini_parts(
    transcript: str,
    frames: list[dict],
    *,
    provider: str = "gemini",
    image_limit: int = GEMINI_IMAGE_HARD_LIMIT,
    prompt_text: str | None = None,
) -> tuple[list, dict]:
    selected    = select_frames(frames, image_limit=image_limit)
    slide_count = sum(1 for f in selected if "type=slide"      in f.get("marker", ""))
    annot_count = sum(1 for f in selected if "type=annotation" in f.get("marker", ""))

    if prompt_text is None:
        prompt_text = QWEN_NOTEBOOKLM_PROMPT_TEXT if provider == "qwen" else GEMINI_PROMPT_TEXT
    parts: list = [prompt_text, transcript]
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


# ── Qwen sliding-window planning ──────────────────────────────────────────────

def _frame_type(frame: dict) -> str:
    marker = frame.get("marker", "")
    if "type=slide" in marker:
        return "slide"
    if "type=annotation" in marker:
        return "annotation"
    return "context"


def _frame_type_counts(frames: list[dict]) -> dict:
    counts = {"slide": 0, "annotation": 0, "context": 0}
    for frame in frames:
        counts[_frame_type(frame)] += 1
    return counts


def load_chunk_segments(chunk_files: list[Path]) -> list[dict]:
    """Load transcript chunks with estimated start/end seconds for window slicing."""
    sorted_files = sorted(chunk_files, key=parse_chunk_start)
    starts = [parse_chunk_start(cf) for cf in sorted_files]
    segments: list[dict] = []
    for idx, cf in enumerate(sorted_files):
        start_s = starts[idx]
        if idx + 1 < len(starts):
            end_s = starts[idx + 1]
        elif idx > 0:
            end_s = start_s + max(1, starts[idx] - starts[idx - 1])
        else:
            end_s = start_s + 60
        text = cf.read_text(encoding="utf-8").strip() if cf.exists() else ""
        segments.append({"start_s": start_s, "end_s": end_s, "text": text})
    return segments


def _transcript_for_window(segments: list[dict], start_s: int, end_s: int) -> str:
    parts = [
        seg["text"]
        for seg in segments
        if seg["text"] and seg["end_s"] >= start_s and seg["start_s"] <= end_s
    ]
    return "\n".join(parts)


def build_qwen_windows(
    chunk_files: list[Path],
    transcript: str,
    frames: list[dict],
    *,
    max_frames: int = QWEN_IMAGE_HARD_LIMIT,
    target_new_frames: int = QWEN_WINDOW_TARGET_FRAMES,
    overlap_frames: int = QWEN_WINDOW_OVERLAP_FRAMES,
) -> list[dict]:
    """Create dynamic Qwen windows that cover all frames without exceeding cap."""
    if max_frames <= 0:
        max_frames = QWEN_IMAGE_HARD_LIMIT
    max_frames = min(max_frames, QWEN_IMAGE_HARD_LIMIT)
    target_new_frames = max(1, min(target_new_frames, max_frames))
    overlap_frames = max(0, min(overlap_frames, max(0, (max_frames - target_new_frames) // 2)))
    # When target was clamped to max_frames (e.g. max_frames=128 < QWEN_WINDOW_TARGET_FRAMES=200),
    # overlap collapses to 0 and windows become coarse (6 windows instead of 8 for 696 frames).
    # Restore overlap by shrinking target: target = max_frames - 2*overlap, giving finer windows.
    if overlap_frames == 0 and target_new_frames == max_frames and max_frames > 2 * QWEN_WINDOW_OVERLAP_FRAMES:
        overlap_frames = QWEN_WINDOW_OVERLAP_FRAMES
        target_new_frames = max(1, max_frames - 2 * overlap_frames)

    segments = load_chunk_segments(chunk_files)
    if not frames:
        start_s = segments[0]["start_s"] if segments else 0
        end_s = segments[-1]["end_s"] if segments else 0
        return [{
            "index": 1,
            "start_s": start_s,
            "end_s": end_s,
            "frames": [],
            "new_frame_count": 0,
            "selected_frame_count": 0,
            "overlap_frame_count": 0,
            "frame_type_counts": {"slide": 0, "annotation": 0, "context": 0},
            "transcript": transcript,
            "transcript_chars": len(transcript.strip()),
            "has_overlap": False,
        }]

    windows: list[dict] = []
    total = len(frames)
    new_start = 0
    while new_start < total:
        new_end = min(total, new_start + target_new_frames)
        left = max(0, new_start - overlap_frames)
        right = min(total, new_end + overlap_frames)

        # Keep total frame count under the provider hard cap. Prefer preserving
        # the new frame span; trim overlap first.
        if right - left > max_frames:
            extra = right - left - max_frames
            trim_left = min(extra, max(0, new_start - left))
            left += trim_left
            extra -= trim_left
            if extra > 0:
                trim_right = min(extra, max(0, right - new_end))
                right -= trim_right
                extra -= trim_right
            if extra > 0:
                right = min(total, left + max_frames)

        window_frames = frames[left:right]
        start_s = int(window_frames[0].get("timestamp_s", 0))
        end_s = int(window_frames[-1].get("timestamp_s", start_s))
        transcript_slice = _transcript_for_window(segments, start_s - 60, end_s + 60)
        if not transcript_slice:
            transcript_slice = transcript

        overlap_count = len(window_frames) - (new_end - new_start)
        windows.append({
            "index": len(windows) + 1,
            "start_s": start_s,
            "end_s": end_s,
            "new_frame_start_index": new_start,
            "new_frame_end_index": new_end,
            "selected_frame_count": len(window_frames),
            "new_frame_count": new_end - new_start,
            "overlap_frame_count": max(0, overlap_count),
            "frame_type_counts": _frame_type_counts(window_frames),
            "frames": window_frames,
            "transcript": transcript_slice,
            "transcript_chars": len(transcript_slice.strip()),
            "has_overlap": left < new_start or right > new_end,
        })
        new_start = new_end

    return windows


def summarize_qwen_windows(windows: list[dict], total_frames: int) -> dict:
    covered_new_frames = sum(w["new_frame_count"] for w in windows)
    selected_frames = sum(w["selected_frame_count"] for w in windows)
    overlap_frames = sum(w["overlap_frame_count"] for w in windows)
    type_counts = {"slide": 0, "annotation": 0, "context": 0}
    for window in windows:
        for key, value in window["frame_type_counts"].items():
            type_counts[key] += value
    return {
        "window_count": len(windows),
        "total_frames": total_frames,
        "covered_new_frames": covered_new_frames,
        "selected_frames_across_windows": selected_frames,
        "overlap_frames": overlap_frames,
        "dropped_frames": max(0, total_frames - covered_new_frames),
        "frame_type_counts_across_windows": type_counts,
        "windows": [
            {
                "index": w["index"],
                "start_s": w["start_s"],
                "end_s": w["end_s"],
                "selected_frame_count": w["selected_frame_count"],
                "new_frame_count": w["new_frame_count"],
                "overlap_frame_count": w["overlap_frame_count"],
                "transcript_chars": w["transcript_chars"],
                "frame_type_counts": w["frame_type_counts"],
            }
            for w in windows
        ],
    }


def qwen_window_note_path(runs_dir: Path, base: str, selected_ts: str, window: dict) -> Path:
    return runs_dir / (
        f"stream-{base}-{selected_ts}.qwen-window-"
        f"{window['index']:03d}.notes.md"
    )


def qwen_window_source_hash(window: dict, *, model: str) -> str:
    """Hash the window source and prompt contract so stale notes are not reused."""
    h = hashlib.sha256()
    h.update(QWEN_WINDOW_NOTE_VERSION.encode("utf-8"))
    h.update(model.encode("utf-8"))
    h.update(QWEN_WINDOW_NOTE_PROMPT_TEXT.encode("utf-8"))
    h.update(str(window.get("start_s", 0)).encode("ascii"))
    h.update(str(window.get("end_s", 0)).encode("ascii"))
    h.update(window.get("transcript", "").encode("utf-8"))
    for frame in window.get("frames", []):
        fp = Path(frame.get("path", ""))
        h.update(str(frame.get("timestamp_s", "")).encode("utf-8"))
        h.update(frame.get("marker", "").encode("utf-8"))
        h.update(str(fp).encode("utf-8"))
        if fp.exists():
            st = fp.stat()
            h.update(str(st.st_size).encode("ascii"))
            h.update(str(st.st_mtime_ns).encode("ascii"))
        else:
            h.update(b"missing")
    return h.hexdigest()


def build_qwen_window_note_metadata(
    window: dict,
    *,
    model: str,
    source_hash: str,
    frame_policy: dict,
    result: dict | None = None,
) -> dict:
    result = result or {}
    return {
        "format": "qwen_window_note",
        "version": QWEN_WINDOW_NOTE_VERSION,
        "model": model,
        "source_hash": source_hash,
        "window_index": window["index"],
        "start_s": window["start_s"],
        "end_s": window["end_s"],
        "selected_frame_count": window["selected_frame_count"],
        "new_frame_count": window["new_frame_count"],
        "overlap_frame_count": window["overlap_frame_count"],
        "transcript_chars": window["transcript_chars"],
        "frame_type_counts": window["frame_type_counts"],
        "frame_policy": frame_policy,
        "api_calls": result.get("api_calls", 0),
        "finish_reason": result.get("finish_reason", ""),
        "usage": result.get("usage", {}),
    }


def write_qwen_window_note(note_path: Path, metadata: dict, text: str) -> None:
    header = [
        "<!-- qwen_window_note",
        json.dumps(metadata, ensure_ascii=False, sort_keys=True),
        "-->",
        "",
    ]
    note_path.write_text("\n".join(header) + text.strip() + "\n", encoding="utf-8")


def read_qwen_window_note_if_current(note_path: Path, source_hash: str) -> dict | None:
    if not note_path.exists():
        return None
    text = note_path.read_text(encoding="utf-8")
    m = re.match(r'<!-- qwen_window_note\s*\n(.*?)\n-->\s*\n?', text, re.S)
    if not m:
        return None
    try:
        metadata = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    if metadata.get("version") != QWEN_WINDOW_NOTE_VERSION:
        return None
    if metadata.get("source_hash") != source_hash:
        return None
    return {
        "metadata": metadata,
        "text": text[m.end():].strip(),
    }


def _context_snippet(text: str, needle: str, radius: int = 80) -> str:
    idx = text.find(needle)
    if idx < 0:
        return ""
    start = max(0, idx - radius)
    end = min(len(text), idx + len(needle) + radius)
    return re.sub(r'\s+', ' ', text[start:end]).strip()


def _fact_aliases(value: str) -> list[str]:
    aliases = [value]
    if value == "Coze":
        aliases.append("扣子")
    elif value == "扣子":
        aliases.append("Coze")
    elif value == "Context Compression":
        aliases.extend(["上下文压缩", "CC"])
    elif value == "Dreamina":
        aliases.append("即梦")
    elif value == "即梦":
        aliases.append("Dreamina")
    elif value == "75分":
        aliases.extend(["75 分", "75"])
    elif value == "99.9%":
        aliases.append("99.9％")
    elif value == "4万积分":
        aliases.append("4 万积分")
    elif value == "19.9万积分":
        aliases.append("19.9 万积分")
    elif value == "30万积分":
        aliases.append("30 万积分")
    return list(dict.fromkeys(aliases))


def extract_qwen_critical_facts(note_texts: list[str]) -> list[dict]:
    """Deterministically extract must-retain facts from Qwen window notes."""
    facts: list[dict] = []
    seen: set[str] = set()

    def add_fact(kind: str, value: str, window_index: int, source_text: str) -> None:
        value = value.strip()
        if not value:
            return
        key = re.sub(r'\s+', '', value.lower())
        if key in seen:
            return
        seen.add(key)
        facts.append({
            "kind": kind,
            "value": value,
            "aliases": _fact_aliases(value),
            "window_index": window_index,
            "context": _context_snippet(source_text, value),
        })

    for idx, text in enumerate(note_texts, start=1):
        for term in QWEN_CRITICAL_FACT_TERMS:
            if term in text:
                kind = "term"
                if term.endswith("分"):
                    kind = "score"
                elif term.endswith("积分"):
                    kind = "cost"
                elif term.endswith("年") or term.endswith("岁"):
                    kind = "date_or_age"
                elif term in {"所见即所得", "不要替换"}:
                    kind = "prompt_keyword"
                elif term in {"Remotion", "HyperFrames", "Coze", "扣子", "Context Compression", "即梦", "Dreamina", "FDE"}:
                    kind = "tool_or_concept"
                add_fact(kind, term, idx, text)

        for pattern, kind in [
            (r'\d+(?:\.\d+)?\s*%', "percentage"),
            (r'\d+(?:\.\d+)?\s*分(?!钟)', "score"),
            (r'\d+(?:\.\d+)?\s*万?\s*积分', "cost"),
            (r'20\d{2}年', "date_or_age"),
            (r'\d+\s*岁', "date_or_age"),
        ]:
            for m in re.finditer(pattern, text):
                add_fact(kind, re.sub(r'\s+', '', m.group(0)), idx, text)

    return facts


def format_qwen_critical_facts_for_prompt(facts: list[dict]) -> str:
    if not facts:
        return "## Critical Facts Checklist\n\n未从窗口笔记中检测到必须保留的关键事实。\n"
    lines = [
        "## Critical Facts Checklist",
        "",
        "以下事实由程序从 Qwen window notes 中确定性抽取。最终 Markdown 必须逐项保留；"
        "可在正文或 `## 5. 技术资产附录：Prompts / Code / Config` 中落地。",
        "",
    ]
    for i, fact in enumerate(facts, start=1):
        aliases = ", ".join(fact.get("aliases") or [fact["value"]])
        context = fact.get("context", "")
        lines.append(
            f"{i}. [{fact['kind']}] `{fact['value']}`"
            f" | aliases: {aliases}"
            f" | source window: {fact['window_index']}"
        )
        if context:
            lines.append(f"   - context: {context}")
    return "\n".join(lines) + "\n"


def _strip_markdown_noise(text: str) -> str:
    text = re.sub(r'```.*?```', ' ', text, flags=re.S)
    text = re.sub(r'<!--.*?-->', ' ', text, flags=re.S)
    text = re.sub(r'(?m)^#{1,6}\s+', '', text)
    text = re.sub(r'(?m)^\s*[-*]\s+', '', text)
    return re.sub(r'\s+', ' ', text).strip()


def _narrative_anchor(text: str) -> str:
    cleaned = _strip_markdown_noise(text)
    return cleaned[:80]


def extract_qwen_narrative_blocks(note_texts: list[str]) -> list[dict]:
    """Extract long narrative evidence blocks from Qwen window notes.

    New notes should include an explicit "Narrative Evidence Blocks" section.
    For older notes, fall back to longer faithful-note paragraphs so QC can still
    measure whether the final body retained story-like content.
    """
    blocks: list[dict] = []
    seen: set[str] = set()

    def add_block(window_index: int, title: str, body: str, time_range: str = "") -> None:
        cleaned = _strip_markdown_noise(body)
        if len(cleaned) < 180:
            return
        key = cleaned[:120]
        if key in seen:
            return
        seen.add(key)
        blocks.append({
            "window_index": window_index,
            "title": title.strip() or f"Window {window_index} narrative evidence",
            "time_range": time_range.strip(),
            "chars": len(cleaned),
            "anchor": _narrative_anchor(cleaned),
            "text": cleaned,
        })

    for window_index, note in enumerate(note_texts, start=1):
        section_match = re.search(
            r'(?ims)^##\s+Narrative Evidence Blocks\s*(.*?)(?=^##\s+|\Z)',
            note,
        )
        if section_match:
            section = section_match.group(1).strip()
            matches = list(re.finditer(
                r'(?ims)^###\s+Narrative Block\s*(?:\[(.*?)\])?\s*(.*?)\n(.*?)(?=^###\s+Narrative Block|\Z)',
                section,
            ))
            if matches:
                for m in matches:
                    add_block(window_index, m.group(2), m.group(3), m.group(1) or "")
            else:
                for i, para in enumerate(re.split(r'\n\s*\n+', section), start=1):
                    add_block(window_index, f"Narrative block {i}", para)
            continue

        faithful = re.search(
            r'(?ims)^##\s+Faithful Notes\s*(.*?)(?=^##\s+Preserved Prompts|^##\s+Visual Evidence|^##\s+Quotes|^##\s+Merge Hints|\Z)',
            note,
        )
        fallback = faithful.group(1) if faithful else note
        candidates = re.split(r'\n\s*\n+', fallback)
        added = 0
        for i, para in enumerate(candidates, start=1):
            if added >= QWEN_NARRATIVE_MIN_BLOCKS_PER_WINDOW:
                break
            if any(marker in para for marker in ["```", "Window Metadata", "Preserved Prompts"]):
                continue
            before = len(blocks)
            add_block(window_index, f"Fallback narrative block {i}", para)
            if len(blocks) > before:
                added += 1

    return blocks


def format_qwen_narrative_blocks_for_prompt(blocks: list[dict]) -> str:
    if not blocks:
        return "## Narrative Evidence Blocks\n\n未从窗口笔记中检测到长叙事证据块。\n"
    lines = [
        "## Narrative Evidence Blocks",
        "",
        "以下长叙事证据由程序从 Qwen window notes 中抽取。最终 Markdown 必须吸收其细节，"
        "并在正文或 `## 6. 叙事证据附录` 中保留。不要压缩成思维导图短句。",
        "",
    ]
    for i, block in enumerate(blocks, start=1):
        time_part = f" [{block['time_range']}]" if block.get("time_range") else ""
        lines.append(f"### Narrative Evidence {i}{time_part} - {block['title']} (window {block['window_index']})")
        lines.append(block["text"])
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def check_qwen_fact_retention(markdown_body: str, facts: list[dict]) -> dict:
    if not facts:
        return {"warnings": [], "metrics": {"fact_count": 0, "retained_count": 0, "retention_ratio": 1.0, "missing_facts": []}}

    missing = []
    retained = 0
    for fact in facts:
        aliases = fact.get("aliases") or [fact["value"]]
        if any(alias and alias in markdown_body for alias in aliases):
            retained += 1
        else:
            missing.append({
                "kind": fact["kind"],
                "value": fact["value"],
                "window_index": fact.get("window_index"),
            })
    ratio = retained / max(1, len(facts))
    warnings = []
    if missing:
        warnings.append(
            "qwen_critical_facts_missing: "
            + ", ".join(f"{m['value']}(w{m['window_index']})" for m in missing[:20])
        )
    if ratio < QWEN_FACT_RETENTION_MIN_RATIO:
        warnings.append(
            f"qwen_fact_retention_low: retained {retained}/{len(facts)}"
            f" ({ratio:.2f}), expected >= {QWEN_FACT_RETENTION_MIN_RATIO:.2f}"
        )
    return {
        "warnings": warnings,
        "metrics": {
            "fact_count": len(facts),
            "retained_count": retained,
            "retention_ratio": round(ratio, 4),
            "missing_facts": missing,
            "min_retention_ratio": QWEN_FACT_RETENTION_MIN_RATIO,
        },
    }


def format_qwen_critical_fact_appendix(facts: list[dict]) -> str:
    if not facts:
        return ""
    lines = [
        "## 7. 关键事实索引",
        "",
        "> 以下索引由程序从 Qwen window notes 确定性生成，用于避免关键数字、年份、评分、时长和工具名在最终组装时被压缩丢失。",
        "",
        "| # | 类型 | 事实 | 来源窗口 | 上下文 |",
        "|---|---|---|---:|---|",
    ]
    for idx, fact in enumerate(facts, start=1):
        context = _strip_markdown_noise(str(fact.get("context", "")))
        context = context.replace("|", " / ")
        if len(context) > 180:
            context = context[:177].rstrip() + "..."
        value = str(fact.get("value", "")).replace("|", " / ")
        kind = str(fact.get("kind", "")).replace("|", " / ")
        window_index = fact.get("window_index", "")
        lines.append(f"| {idx} | {kind} | {value} | {window_index} | {context} |")
    return "\n".join(lines).strip() + "\n"


def ensure_qwen_critical_fact_appendix(markdown_body: str, facts: list[dict]) -> tuple[str, dict]:
    if not facts:
        return markdown_body, {"appended": False, "reason": "no_facts", "appended_facts": 0}
    if "## 7. 关键事实索引" in markdown_body or "## 关键事实索引" in markdown_body:
        retention = check_qwen_fact_retention(markdown_body, facts)
        if not retention["metrics"]["missing_facts"]:
            return markdown_body, {
                "appended": False,
                "reason": "already_present",
                "appended_facts": 0,
                "source_metrics": retention["metrics"],
            }

    marker = "<!-- qwen_window_coverage:"
    coverage_tail = ""
    body = markdown_body.rstrip()
    if marker in body:
        idx = body.rfind(marker)
        coverage_tail = body[idx:].strip()
        body = body[:idx].rstrip()

    appendix = format_qwen_critical_fact_appendix(facts)
    if "## 7. 关键事实索引" in body or "## 关键事实索引" in body:
        appendix = appendix.replace("## 7. 关键事实索引", "## 7. 关键事实索引（程序补全）", 1)
    updated = body + "\n\n" + appendix.rstrip() + "\n"
    if coverage_tail:
        updated += "\n" + coverage_tail + "\n"
    retention = check_qwen_fact_retention(updated, facts)
    return updated, {
        "appended": True,
        "reason": "deterministic_source_retention",
        "appended_facts": len(facts),
        "source_metrics": retention["metrics"],
    }


def check_qwen_timeline_overlaps(markdown_body: str) -> dict:
    chapters = []
    for m in re.finditer(
        r'(?m)^###\s+\[(\d{2}):(\d{2}):(\d{2})\s*-\s*(\d{2}):(\d{2}):(\d{2})\]\s*(.*)$',
        markdown_body,
    ):
        sh, sm, ss, eh, em, es, title = m.groups()
        start = int(sh) * 3600 + int(sm) * 60 + int(ss)
        end = int(eh) * 3600 + int(em) * 60 + int(es)
        chapters.append({"start_s": start, "end_s": end, "title": title.strip()})

    overlaps = []
    prev = None
    for chapter in chapters:
        if prev and chapter["start_s"] < prev["end_s"]:
            overlaps.append({
                "previous": prev,
                "current": chapter,
                "overlap_s": prev["end_s"] - chapter["start_s"],
            })
        if prev is None or chapter["end_s"] > prev["end_s"]:
            prev = chapter

    warnings = []
    if overlaps:
        warnings.append(
            "qwen_timeline_overlaps: "
            + "; ".join(
                f"{fmt_ts(o['current']['start_s'])}-{fmt_ts(o['previous']['end_s'])}"
                for o in overlaps[:10]
            )
        )
    return {
        "warnings": warnings,
        "metrics": {
            "chapter_count": len(chapters),
            "overlap_count": len(overlaps),
            "overlaps": overlaps,
        },
    }


def check_qwen_technical_asset_appendix(markdown_body: str, facts: list[dict]) -> dict:
    has_section = "## 5. 技术资产附录" in markdown_body or "## 技术资产附录" in markdown_body
    code_fence_count = markdown_body.count("```") // 2
    prompt_facts = [
        f for f in facts
        if f.get("kind") in {"prompt_keyword", "tool_or_concept"} or f.get("value") in {"所见即所得", "不要替换"}
    ]
    warnings = []
    if prompt_facts and not has_section:
        warnings.append("qwen_missing_technical_asset_appendix: expected Prompts / Code / Config appendix")
    if prompt_facts and code_fence_count < 2:
        warnings.append("qwen_technical_asset_code_blocks_low: expected preserved prompt/code/config fences")
    return {
        "warnings": warnings,
        "metrics": {
            "has_technical_asset_appendix": has_section,
            "code_fence_count": code_fence_count,
            "prompt_fact_count": len(prompt_facts),
        },
    }


def check_frame_timestamp_alignment(frames: list[dict], manifest: dict) -> dict:
    timeline_end_s = int(manifest.get("timeline_end_s", 0) or 0)
    if not frames or timeline_end_s <= 0:
        return {
            "warnings": [],
            "metrics": {
                "frame_count": len(frames),
                "max_frame_timestamp_s": 0,
                "timeline_end_s": timeline_end_s,
                "timestamp_scope_counts": {},
            },
        }

    max_ts = max(int(f.get("timestamp_s", 0) or 0) for f in frames)
    min_ts = min(int(f.get("timestamp_s", 0) or 0) for f in frames)
    scope_counts: dict[str, int] = {}
    for frame in frames:
        scope = str(frame.get("timestamp_scope", "unknown"))
        scope_counts[scope] = scope_counts.get(scope, 0) + 1

    warnings = []
    if max_ts > timeline_end_s + BODY_COVERAGE_GAP_S:
        warnings.append(
            f"frame_timestamp_exceeds_timeline: max frame {fmt_ts(max_ts)},"
            f" timeline end {fmt_ts(timeline_end_s)}"
        )
    return {
        "warnings": warnings,
        "metrics": {
            "frame_count": len(frames),
            "min_frame_timestamp_s": min_ts,
            "max_frame_timestamp_s": max_ts,
            "timeline_end_s": timeline_end_s,
            "max_frame_tail_delta_s": max_ts - timeline_end_s,
            "timestamp_scope_counts": scope_counts,
        },
    }


def check_qwen_narrative_retention(markdown_body: str, blocks: list[dict], transcript: str) -> dict:
    transcript_chars = max(1, len(transcript.strip()))
    body_chars = len(markdown_body.strip())
    body_ratio = body_chars / transcript_chars

    if not blocks:
        return {
            "warnings": ["qwen_narrative_blocks_missing: no narrative evidence blocks extracted"],
            "metrics": {
                "narrative_block_count": 0,
                "retained_block_count": 0,
                "retention_ratio": 0,
                "body_transcript_ratio": round(body_ratio, 4),
                "min_body_transcript_ratio": QWEN_NARRATIVE_RETENTION_MIN_RATIO,
                "missing_blocks": [],
            },
        }

    missing = []
    retained = 0
    for block in blocks:
        anchor = block.get("anchor", "")
        text = block.get("text", "")
        probes = [anchor[:50], anchor[:35], text[:80], text[:50]]
        if any(probe and probe in markdown_body for probe in probes):
            retained += 1
        else:
            missing.append({
                "window_index": block.get("window_index"),
                "title": block.get("title"),
                "anchor": anchor[:80],
            })
    retention_ratio = retained / max(1, len(blocks))
    warnings = []
    if body_ratio < QWEN_NARRATIVE_RETENTION_MIN_RATIO:
        warnings.append(
            f"qwen_narrative_body_ratio_low: body/transcript ratio {body_ratio:.2f},"
            f" expected >= {QWEN_NARRATIVE_RETENTION_MIN_RATIO:.2f}"
        )
    if missing:
        warnings.append(
            "qwen_narrative_blocks_missing_from_final: "
            + ", ".join(f"w{m['window_index']}:{m['title']}" for m in missing[:10])
        )
    return {
        "warnings": warnings,
        "metrics": {
            "narrative_block_count": len(blocks),
            "retained_block_count": retained,
            "retention_ratio": round(retention_ratio, 4),
            "body_transcript_ratio": round(body_ratio, 4),
            "min_body_transcript_ratio": QWEN_NARRATIVE_RETENTION_MIN_RATIO,
            "missing_blocks": missing,
        },
    }


def ensure_qwen_narrative_appendix(markdown_body: str, blocks: list[dict], transcript: str) -> tuple[str, dict]:
    """Deterministically append narrative evidence if final assembly compresses it."""
    if not blocks:
        return markdown_body, {"appended": False, "reason": "no_blocks", "appended_blocks": 0}

    retention = check_qwen_narrative_retention(markdown_body, blocks, transcript)
    metrics = retention["metrics"]
    has_section = "## 6. 叙事证据附录" in markdown_body or "## 叙事证据附录" in markdown_body
    should_append = (
        not has_section
        or metrics["body_transcript_ratio"] < QWEN_NARRATIVE_RETENTION_MIN_RATIO
        or metrics["retention_ratio"] < 0.80
    )
    if not should_append:
        return markdown_body, {"appended": False, "reason": "already_retained", "appended_blocks": 0}

    marker = "<!-- qwen_window_coverage:"
    coverage_tail = ""
    body = markdown_body.rstrip()
    if marker in body:
        idx = body.rfind(marker)
        coverage_tail = body[idx:].strip()
        body = body[:idx].rstrip()

    lines = [
        "",
        "## 6. 叙事证据附录",
        "",
        "> 以下内容由程序从 Qwen window notes 确定性追加，用于避免长文叙事在最终组装时被压缩丢失。",
        "",
    ]
    for i, block in enumerate(blocks, start=1):
        time_part = f" [{block['time_range']}]" if block.get("time_range") else ""
        lines.append(f"### Narrative Evidence {i}{time_part} - {block['title']} (window {block['window_index']})")
        lines.append(block["text"])
        lines.append("")
    if coverage_tail:
        lines.append(coverage_tail)
    return body + "\n" + "\n".join(lines).rstrip() + "\n", {
        "appended": True,
        "reason": "missing_or_low_retention",
        "appended_blocks": len(blocks),
        "pre_append_metrics": metrics,
    }


def add_usage(a: dict, b: dict) -> dict:
    return {
        "input_tokens": int(a.get("input_tokens", 0)) + int(b.get("input_tokens", 0)),
        "output_tokens": int(a.get("output_tokens", 0)) + int(b.get("output_tokens", 0)),
        "total_tokens": int(a.get("total_tokens", 0)) + int(b.get("total_tokens", 0)),
    }


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


def check_qwen_notebooklm_quality(markdown_body: str, transcript: str, manifest: dict) -> dict:
    """Detect Qwen outputs that are too compressed for NotebookLM source use."""
    body = markdown_body.strip()
    transcript_chars = max(1, len(transcript.strip()))
    body_chars = len(body)
    body_ratio = body_chars / transcript_chars

    h1_exists = bool(re.search(r'(?m)^#\s+[^#\s].+', body))
    required_sections = [
        "## 1. 视频元数据",
        "## 2. 核心知识字典",
        "## 3. 详尽内容解析",
    ]
    missing_sections = [s for s in required_sections if s not in body]
    chapter_count = len(re.findall(r'(?m)^###\s+\[\d{2}:\d{2}:\d{2}\s+-\s+\d{2}:\d{2}:\d{2}\]', body))
    field_names = ["**核心论点：**", "**详细展开：**", "**视觉/屏幕内容：**", "**重要金句/原话：**"]
    missing_chapter_fields = [name for name in field_names if chapter_count and name not in body]

    code_fence_count = body.count("```")
    source_prompt_markers = ["Prompt", "prompt", "提示词", "所见即所得", "不要替换", "配置", "代码"]
    source_has_prompt_like_detail = any(marker in transcript for marker in source_prompt_markers)
    missing_prompt_markers = [
        marker for marker in ["提示词", "所见即所得", "不要替换"]
        if marker in transcript and marker not in body
    ]

    warnings: list[str] = []
    if not h1_exists:
        warnings.append("qwen_missing_h1: final body must start with a concrete H1 title")
    if missing_sections:
        warnings.append("qwen_missing_required_sections: " + ", ".join(missing_sections))
    if chapter_count == 0:
        warnings.append("qwen_missing_timestamped_chapters: no ### [HH:MM:SS - HH:MM:SS] chapters found")
    if missing_chapter_fields:
        warnings.append("qwen_missing_chapter_fields: " + ", ".join(missing_chapter_fields))
    if body_ratio < QWEN_BODY_MIN_TRANSCRIPT_RATIO:
        warnings.append(
            f"qwen_overcompressed_body: body/transcript ratio {body_ratio:.2f},"
            f" expected >= {QWEN_BODY_MIN_TRANSCRIPT_RATIO:.2f}"
        )
    if source_has_prompt_like_detail and code_fence_count < 2:
        warnings.append(
            "qwen_missing_code_blocks: source contains prompt/config/code-like details"
            " but model body has no fenced code block"
        )
    if missing_prompt_markers:
        warnings.append("qwen_missing_prompt_keywords: " + ", ".join(missing_prompt_markers))

    return {
        "warnings": warnings,
        "metrics": {
            "h1_exists": h1_exists,
            "body_chars": body_chars,
            "body_transcript_ratio": round(body_ratio, 4),
            "required_sections_missing": missing_sections,
            "timestamped_chapter_count": chapter_count,
            "chapter_fields_missing": missing_chapter_fields,
            "code_fence_count": code_fence_count,
            "prompt_keywords_missing": missing_prompt_markers,
            "body_min_transcript_ratio": QWEN_BODY_MIN_TRANSCRIPT_RATIO,
            "source_frame_count": manifest.get("frame_count", 0),
        },
    }


def check_qwen_window_coverage(markdown_body: str, manifest: dict) -> dict:
    policy = manifest.get("qwen_window_policy") or {}
    windows = policy.get("windows") or []
    expected = {int(w["index"]) for w in windows if "index" in w}
    if not expected:
        return {"warnings": [], "metrics": {"expected_windows": [], "covered_windows": []}}

    m = re.search(r'<!--\s*qwen_window_coverage:\s*([0-9,\s]+)\s*-->', markdown_body)
    if not m:
        return {
            "warnings": ["qwen_window_unreferenced: missing qwen_window_coverage marker"],
            "metrics": {
                "expected_windows": sorted(expected),
                "covered_windows": [],
                "missing_windows": sorted(expected),
            },
        }
    covered = {
        int(part.strip())
        for part in m.group(1).split(",")
        if part.strip().isdigit()
    }
    missing = sorted(expected - covered)
    warnings = []
    if missing:
        warnings.append("qwen_window_unreferenced: missing windows " + ",".join(map(str, missing)))
    return {
        "warnings": warnings,
        "metrics": {
            "expected_windows": sorted(expected),
            "covered_windows": sorted(covered),
            "missing_windows": missing,
        },
    }


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
        else:
            lines.append(f"> - ⚠️ {w}")

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
    ap.add_argument("--synthesis-pass", choices=("one-shot", "sliding-window"), default="one-shot",
                    help="Synthesis strategy; sliding-window is Qwen-only and explicit opt-in")
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
    ap.add_argument("--resume-window-notes", action="store_true",
                    help="Qwen sliding-window only: reuse existing window notes when source hashes match")
    args = ap.parse_args()

    provider = args.provider
    synthesis_pass = args.synthesis_pass
    if synthesis_pass == "sliding-window" and provider != "qwen":
        print("ERROR: --synthesis-pass sliding-window is only supported with --provider qwen",
              file=sys.stderr)
        sys.exit(2)
    if args.resume_window_notes and synthesis_pass != "sliding-window":
        print("ERROR: --resume-window-notes requires --synthesis-pass sliding-window",
              file=sys.stderr)
        sys.exit(2)
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

    # Auto-route: Qwen + long transcript → sliding-window regardless of caller.
    # Covers live stream, replay, and local MP4 paths uniformly.
    if (provider == "qwen" and synthesis_pass == "one-shot"
            and len(transcript) > QWEN_AUTO_SLIDING_WINDOW_CHARS):
        synthesis_pass = "sliding-window"
        print(
            f"[auto-route] transcript {len(transcript):,} chars"
            f" > {QWEN_AUTO_SLIDING_WINDOW_CHARS:,}: Qwen one-shot → sliding-window",
            flush=True,
        )

    manifest["synthesis_pass"] = synthesis_pass
    frame_timestamp = check_frame_timestamp_alignment(all_frames, manifest)
    manifest["frame_timestamp_qc"] = frame_timestamp["metrics"]
    manifest["warnings"].extend(frame_timestamp["warnings"])
    if provider == "qwen":
        manifest["qwen_thinking_enabled"] = bool(args.qwen_thinking)
    label_part = f".{output_label}" if output_label else ""
    qc_path  = runs_dir / f"stream-{args.base}-{selected_ts}{label_part}.final-qc.json"
    qc_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"QC manifest : {qc_path}  [{manifest['source_status']}]")
    for w in manifest["warnings"]:
        print(f"  [warn] {w}")

    provider_image_limit = GEMINI_IMAGE_HARD_LIMIT if provider == "gemini" else qwen_max_frames
    if args.max_frames > 0:
        image_limit = max(1, min(args.max_frames, provider_image_limit))
    else:
        image_limit = provider_image_limit
    qwen_windows: list[dict] = []
    qwen_window_summary: dict | None = None
    if synthesis_pass == "sliding-window":
        qwen_windows = build_qwen_windows(
            chunk_files,
            transcript,
            all_frames,
            max_frames=image_limit,
        )
        qwen_window_summary = summarize_qwen_windows(qwen_windows, len(all_frames))
        manifest["qwen_window_policy"] = qwen_window_summary
        manifest["warnings"].extend(
            [] if qwen_window_summary["dropped_frames"] == 0 else [
                f"qwen_frame_coverage_low: dropped {qwen_window_summary['dropped_frames']} frames"
            ]
        )
        qc_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    max_successful_calls = 1 + max(0, args.max_continuations)
    if synthesis_pass == "sliding-window":
        max_successful_calls = (len(qwen_windows) + 1) * max_successful_calls
    print(f"\n=== {provider} budget ===")
    print(f"  model                : {provider_model}")
    print(f"  synthesis_pass       : {synthesis_pass}")
    print(f"  max successful calls : {max_successful_calls}")
    print(f"  retry cap            : {args.max_retries}")
    print(f"  image cap            : {image_limit}")
    if qwen_window_summary:
        print(f"  qwen windows         : {qwen_window_summary['window_count']}")
        print(f"  frame coverage       : {qwen_window_summary['covered_new_frames']}/{len(all_frames)}"
              f" new frames, overlap {qwen_window_summary['overlap_frames']}")
    if args.max_frames > 0:
        print(f"  fair A/B max frames  : {args.max_frames}")
    print("  duplicate synthesis  : false")
    if output_label:
        print(f"  output label         : {output_label}")
    if args.mock_gemini_text:
        print(f"  offline validation   : {args.mock_gemini_text} (no API call)")

    if args.dry_run:
        if synthesis_pass == "sliding-window":
            total_parts = 0
            dry_window_policies = []
            for window in qwen_windows:
                window_text = (
                    f"Window {window['index']}/{len(qwen_windows)}\n"
                    f"Time range: {fmt_ts(window['start_s'])} - {fmt_ts(window['end_s'])}\n"
                    f"Frames: {window['selected_frame_count']}\n\n"
                    f"{window['transcript']}"
                )
                dry_parts, dry_policy = build_gemini_parts(
                    window_text,
                    window["frames"],
                    provider=provider,
                    image_limit=image_limit,
                    prompt_text=QWEN_WINDOW_NOTE_PROMPT_TEXT,
                )
                total_parts += len(dry_parts)
                dry_window_policies.append(dry_policy)
            manifest["frame_policy"] = {
                "provider": provider,
                "mode": synthesis_pass,
                "window_count": len(qwen_windows),
                "windows": dry_window_policies,
            }
            manifest["provider_parts_count"] = total_parts
        else:
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
        manifest["synthesis_pass"] = f"mock-{synthesis_pass}"
        manifest["frame_policy"] = {
            "provider": provider,
            "total_frames": len(all_frames),
            "selected_frames": 0,
            "dropped_frames": len(all_frames),
            "cap": image_limit,
        }
    else:
        print(f"\n=== {provider}: Building NotebookLM document ===")
        if provider == "gemini":
            parts, frame_policy = build_gemini_parts(
                transcript,
                all_frames,
                provider=provider,
                image_limit=image_limit,
            )
            manifest["frame_policy"] = frame_policy
            manifest["provider_parts_count"] = len(parts)
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
            if synthesis_pass == "one-shot":
                parts, frame_policy = build_gemini_parts(
                    transcript,
                    all_frames,
                    provider=provider,
                    image_limit=image_limit,
                )
                manifest["frame_policy"] = frame_policy
                manifest["provider_parts_count"] = len(parts)
                _qw_quality_retries = 0
                _QW_QUALITY_MAX_RETRIES = 2
                while True:
                    qwen_result = call_qwen(
                        client, parts, args.base,
                        model=provider_model,
                        enable_thinking=args.qwen_thinking,
                        thinking_budget=args.thinking_budget,
                        max_retries=args.max_retries,
                        max_continuations=args.max_continuations,
                    )
                    gemini_text = qwen_result.get("text")
                    if (gemini_text and transcript and
                            len(gemini_text) / len(transcript) < QWEN_BODY_MIN_TRANSCRIPT_RATIO and
                            _qw_quality_retries < _QW_QUALITY_MAX_RETRIES):
                        _qw_quality_retries += 1
                        print(
                            f"[!] Qwen overcompressed (ratio={len(gemini_text)/len(transcript):.2f}),"
                            f" retry {_qw_quality_retries}/{_QW_QUALITY_MAX_RETRIES}",
                            flush=True,
                        )
                        continue
                    break
                manifest["provider_usage"] = {k: v for k, v in qwen_result.items() if k != "text"}
                if _qw_quality_retries:
                    manifest["provider_usage"]["qwen_quality_retries"] = _qw_quality_retries
            else:
                note_texts: list[str] = []
                note_paths: list[str] = []
                note_metadata_list: list[dict] = []
                current_run_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
                end_to_end_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
                current_run_calls = 0
                end_to_end_calls = 0
                finish_reasons: list[str] = []
                window_policies = []
                reused_window_notes = 0

                for window in qwen_windows:
                    window_label = f"{args.base}-window-{window['index']:03d}"
                    note_path = qwen_window_note_path(runs_dir, args.base, selected_ts, window)
                    source_hash = qwen_window_source_hash(window, model=provider_model)
                    if args.resume_window_notes:
                        cached = read_qwen_window_note_if_current(note_path, source_hash)
                        if cached:
                            note_paths.append(str(note_path))
                            note_texts.append(cached["text"])
                            cached_metadata = cached["metadata"]
                            note_metadata_list.append(cached_metadata)
                            cached_policy = cached_metadata.get("frame_policy", {})
                            if cached_policy:
                                window_policies.append(cached_policy)
                            end_to_end_usage = add_usage(
                                end_to_end_usage,
                                cached_metadata.get("usage", {}),
                            )
                            end_to_end_calls += int(cached_metadata.get("api_calls", 0) or 0)
                            finish_reasons.append(str(cached_metadata.get("finish_reason", "")))
                            reused_window_notes += 1
                            print(f"[{window_label}] Reusing window note: {note_path}", flush=True)
                            continue

                    window_text = (
                        f"Window {window['index']}/{len(qwen_windows)}\n"
                        f"Time range: {fmt_ts(window['start_s'])} - {fmt_ts(window['end_s'])}\n"
                        f"Selected frames: {window['selected_frame_count']}\n"
                        f"New frames: {window['new_frame_count']}\n"
                        f"Overlap frames: {window['overlap_frame_count']}\n\n"
                        f"{window['transcript']}"
                    )
                    parts, frame_policy = build_gemini_parts(
                        window_text,
                        window["frames"],
                        provider=provider,
                        image_limit=image_limit,
                        prompt_text=QWEN_WINDOW_NOTE_PROMPT_TEXT,
                    )
                    window_policies.append(frame_policy)
                    result = call_qwen(
                        client, parts, window_label,
                        model=provider_model,
                        enable_thinking=args.qwen_thinking,
                        thinking_budget=args.thinking_budget,
                        max_retries=args.max_retries,
                        max_continuations=args.max_continuations,
                    )
                    note_text = result.get("text")
                    if not note_text:
                        print(f"[!] qwen window {window['index']} synthesis failed", file=sys.stderr)
                        sys.exit(1)
                    metadata = build_qwen_window_note_metadata(
                        window,
                        model=provider_model,
                        source_hash=source_hash,
                        frame_policy=frame_policy,
                        result=result,
                    )
                    write_qwen_window_note(note_path, metadata, note_text)
                    note_paths.append(str(note_path))
                    note_texts.append(note_text)
                    note_metadata_list.append(metadata)
                    usage = result.get("usage", {})
                    current_run_usage = add_usage(current_run_usage, usage)
                    end_to_end_usage = add_usage(end_to_end_usage, usage)
                    current_run_calls += int(result.get("api_calls", 0) or 0)
                    end_to_end_calls += int(result.get("api_calls", 0) or 0)
                    finish_reasons.append(str(result.get("finish_reason", "")))

                critical_facts = extract_qwen_critical_facts(note_texts)
                narrative_blocks = extract_qwen_narrative_blocks(note_texts)
                critical_facts_block = format_qwen_critical_facts_for_prompt(critical_facts)
                narrative_blocks_block = format_qwen_narrative_blocks_for_prompt(narrative_blocks)
                combined_notes = "\n\n---\n\n".join(
                    f"<!-- window {idx + 1} -->\n{text.strip()}"
                    for idx, text in enumerate(note_texts)
                )
                window_count = len(qwen_windows)
                final_input = (
                    f"[约束] 本次共 {window_count} 个窗口笔记，最终正文章节数必须 ≥ {window_count}，"
                    f"每个窗口对应至少一个独立章节。\n\n"
                    + critical_facts_block
                    + "\n\n"
                    + narrative_blocks_block
                    + "\n\n## Qwen Window Notes\n\n"
                    + combined_notes
                )
                final_result = call_qwen(
                    client,
                    [QWEN_FINAL_ASSEMBLY_PROMPT_TEXT, final_input],
                    f"{args.base}-final-assembly",
                    model=provider_model,
                    enable_thinking=args.qwen_thinking,
                    thinking_budget=args.thinking_budget,
                    max_retries=args.max_retries,
                    max_continuations=args.max_continuations,
                )
                gemini_text = final_result.get("text")
                final_usage = final_result.get("usage", {})
                current_run_usage = add_usage(current_run_usage, final_usage)
                end_to_end_usage = add_usage(end_to_end_usage, final_usage)
                current_run_calls += int(final_result.get("api_calls", 0) or 0)
                end_to_end_calls += int(final_result.get("api_calls", 0) or 0)
                finish_reasons.append(str(final_result.get("finish_reason", "")))
                manifest["frame_policy"] = {
                    "provider": provider,
                    "mode": synthesis_pass,
                    "window_count": len(qwen_windows),
                    "windows": window_policies,
                }
                manifest["provider_parts_count"] = sum(2 + p.get("selected_frames", 0) * 2 for p in window_policies) + 2
                manifest["qwen_window_notes"] = note_paths
                manifest["qwen_window_notes_reused"] = reused_window_notes
                manifest["qwen_window_note_metadata"] = note_metadata_list
                manifest["qwen_final_assembly_version"] = QWEN_FINAL_ASSEMBLY_VERSION
                manifest["qwen_critical_fact_version"] = QWEN_CRITICAL_FACT_VERSION
                manifest["qwen_critical_facts"] = critical_facts
                manifest["qwen_narrative_block_version"] = QWEN_NARRATIVE_BLOCK_VERSION
                manifest["qwen_narrative_blocks"] = narrative_blocks
                manifest["provider_usage"] = {
                    "provider": "qwen",
                    "model": provider_model,
                    "api_calls": current_run_calls,
                    "finish_reason": finish_reasons[-1] if finish_reasons else "",
                    "window_finish_reasons": finish_reasons,
                    "usage": current_run_usage,
                    "current_run_usage": current_run_usage,
                    "current_run_api_calls": current_run_calls,
                    "end_to_end_usage": end_to_end_usage,
                    "end_to_end_api_calls": end_to_end_calls,
                    "reused_window_note_api_calls": end_to_end_calls - current_run_calls,
                    "estimated_cost_cny": None,
                }

    if not gemini_text:
        print(f"[!] {provider} synthesis failed — merged raw transcript still available.",
              file=sys.stderr)
        sys.exit(1)

    if provider == "qwen" and synthesis_pass == "sliding-window":
        gemini_text, narrative_appendix = ensure_qwen_narrative_appendix(
            gemini_text,
            manifest.get("qwen_narrative_blocks", []),
            transcript,
        )
        manifest["qwen_narrative_appendix"] = narrative_appendix
        qwen_facts = manifest.get("qwen_critical_facts", [])
        qwen_fact_body_retention = check_qwen_fact_retention(gemini_text, qwen_facts)
        manifest["qwen_fact_body_retention_qc"] = qwen_fact_body_retention["metrics"]
        manifest["qwen_fact_body_retention_warnings"] = qwen_fact_body_retention["warnings"]
        gemini_text, critical_fact_appendix = ensure_qwen_critical_fact_appendix(
            gemini_text,
            qwen_facts,
        )
        manifest["qwen_critical_fact_appendix"] = critical_fact_appendix

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
    if provider == "qwen":
        qwen_quality = check_qwen_notebooklm_quality(gemini_text, transcript, manifest)
        manifest["qwen_notebooklm_qc"] = qwen_quality["metrics"]
        manifest["warnings"].extend(qwen_quality["warnings"])
        if synthesis_pass == "sliding-window":
            qwen_window_coverage = check_qwen_window_coverage(gemini_text, manifest)
            manifest["qwen_window_coverage_qc"] = qwen_window_coverage["metrics"]
            manifest["warnings"].extend(qwen_window_coverage["warnings"])
            qwen_facts = manifest.get("qwen_critical_facts", [])
            qwen_fact_retention = check_qwen_fact_retention(gemini_text, qwen_facts)
            manifest["qwen_fact_retention_qc"] = qwen_fact_retention["metrics"]
            manifest["warnings"].extend(qwen_fact_retention["warnings"])
            qwen_timeline = check_qwen_timeline_overlaps(gemini_text)
            manifest["qwen_timeline_qc"] = qwen_timeline["metrics"]
            manifest["warnings"].extend(qwen_timeline["warnings"])
            qwen_assets = check_qwen_technical_asset_appendix(gemini_text, qwen_facts)
            manifest["qwen_technical_asset_qc"] = qwen_assets["metrics"]
            manifest["warnings"].extend(qwen_assets["warnings"])
            qwen_narrative = check_qwen_narrative_retention(
                gemini_text,
                manifest.get("qwen_narrative_blocks", []),
                transcript,
            )
            manifest["qwen_narrative_retention_qc"] = qwen_narrative["metrics"]
            manifest["warnings"].extend(qwen_narrative["warnings"])
    manifest["transcript_appendix_chars"] = len(transcript.strip())
    manifest["visual_evidence_count"] = len(all_frames)
    manifest["deterministic_appendices"] = ["full_transcript", "visual_evidence_index"]
    if provider == "qwen" and synthesis_pass == "sliding-window":
        manifest["deterministic_appendices"].insert(0, "critical_fact_index")
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
