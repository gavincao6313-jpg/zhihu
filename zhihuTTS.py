import argparse
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import json
from datetime import date, datetime
from pathlib import Path
from google import genai
from google.genai import types

from zhihuTTS_video import (
    extract_keyframes,
    transcribe_audio,
    transcript_to_text,
    KEYFRAMES_DIR,
    frame_marker,
)

VIDEOS_DIR = Path(__file__).parent / "Videos"
MARKDOWNS_DIR = Path(__file__).parent / "Markdowns"
PROGRESS_FILE = Path(__file__).parent / ".progress.json"
LOG_FILE = Path(__file__).parent / "zhihuTTS.log"
CACHE_DIR = Path(__file__).parent / "cache"
TRANSCRIPT_CACHE_DIR = CACHE_DIR / "transcripts"
KEYFRAME_CACHE_DIR = CACHE_DIR / "keyframes"
PAYLOAD_CACHE_DIR = CACHE_DIR / "payloads"
RUNS_DIR = Path(__file__).parent / "runs"

MAX_RETRIES = 6
RETRY_DELAY = 65
DAILY_QUOTA_LIMIT = 20
GEMINI_MODEL = "gemini-2.5-flash"

PROMPT_TEXT = """
# 角色与目标
你是一个顶级的知识库数据提取专家。我将提供一段视频的**完整逐字稿（带时间戳）**和**关键帧截图（包含幻灯片切换和画笔标注）**，请将它们视为完整的视频内容，提取转化为一份**高度详尽、结构化、完全适合导入 NotebookLM 作为底层语料的 Markdown 文档**。

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

_logger = logging.getLogger("zhihuTTS")


def _setup_logging():
    _logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8", mode="a")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    _logger.addHandler(fh)


def _parse_retry_delay(error: Exception) -> int:
    """从 429 错误信息中提取建议等待秒数，找不到则返回 RETRY_DELAY。"""
    match = re.search(r'retry in (\d+(?:\.\d+)?)s', str(error), re.IGNORECASE)
    return int(float(match.group(1))) + 10 if match else RETRY_DELAY


_print_lock = threading.Lock()
_progress_lock = threading.Lock()

# Gemini API 常量
MAX_CONTINUATIONS = 20  # 自动续写最大次数（单次 ~65K tokens，20次远超实际所需）


def _first_candidate(resp):
    if not resp.candidates:
        reason = getattr(resp, "prompt_feedback", None)
        raise RuntimeError(f"API 返回无 candidates（疑似安全过滤）: {reason}")
    return resp.candidates[0]


def _safe_text(resp):
    try:
        return resp.text
    except ValueError:
        reason = getattr(resp, "prompt_feedback", None)
        raise RuntimeError(f"API 响应被拦截（安全过滤）: {reason}")


def _call_gemini_with_retry(client, parts, video_label) -> dict:
    """调用 Gemini API，含自动续写（MAX_TOKENS）和重试（限流/网络错误）。"""
    gemini_config = types.GenerateContentConfig(
        temperature=0.1,
        max_output_tokens=65536,  # gemini-2.5-flash 的最大输出上限
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )

    gemini_calls = 0
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            tprint(f"[{video_label}] 发送至 Gemini API（{len(parts)} 个输入块）...")
            # 用 chat session 保留多轮上下文，续写时无需手动拼 contents
            chat = client.chats.create(model=GEMINI_MODEL, config=gemini_config)
            gemini_calls += 1
            response = chat.send_message(parts)
            text = _safe_text(response)
            if not text:
                raise RuntimeError("API 返回空响应")

            full_text = text
            candidate = _first_candidate(response)

            # 自动续写：输出被截断时追加 "继续" 直至完整
            for cont in range(MAX_CONTINUATIONS):
                if candidate.finish_reason != types.FinishReason.MAX_TOKENS:
                    break
                tprint(f"[{video_label}] 输出被截断，自动续写 (第{cont+1}次)...")
                gemini_calls += 1
                response = chat.send_message("继续")
                text = _safe_text(response)
                if not text:
                    tprint(f"[{video_label}] ⚠ 续写返回空响应，提前结束")
                    break
                full_text += "\n" + text
                candidate = _first_candidate(response)
            else:
                tprint(f"[{video_label}] ⚠ 续写已达 {MAX_CONTINUATIONS} 次上限，输出可能仍不完整")

            if candidate.finish_reason is not None and candidate.finish_reason != types.FinishReason.STOP:
                fr = candidate.finish_reason
                tprint(f"[{video_label}] ⚠ 输出可能不完整 (finish_reason={fr})，"
                       f"输出 {len(full_text)} 字符")

            return {"text": full_text, "gemini_calls": gemini_calls}

        except Exception as e:
            is_rate_limited = "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)
            if is_rate_limited:
                delay = _parse_retry_delay(e)
                tprint(f"[{video_label}] 触发限流（429），{delay}s 后重试...")
            else:
                delay = RETRY_DELAY
                with _print_lock:
                    print(f"[{video_label}] 失败: {e}", flush=True)
                _logger.error(f"[{video_label}] 失败: {e}", exc_info=True)

            if attempt < MAX_RETRIES:
                time.sleep(delay)
            else:
                tprint(f"[{video_label}] 已达最大重试次数", level="error")

    return {"text": None, "gemini_calls": gemini_calls}


def tprint(msg: str, level: str = "info"):
    with _print_lock:
        print(msg, flush=True)
    getattr(_logger, level)(msg)


def load_progress() -> dict:
    """加载进度，自动迁移旧格式（{name: 'done'} → 新格式）。"""
    default = {"videos": {}, "quota": {}, "last_run": None}
    if not PROGRESS_FILE.exists():
        return default

    try:
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        print("  ⚠ 进度文件损坏或不可读（上次异常退出），已重置配额计数。")
        data = {"videos": {}, "quota": {}, "last_run": None}
        save_progress(data)
        return data

    # 迁移旧格式: {"video": "done"} → {"videos": {"video": {"status": "done", ...}}}
    if "videos" not in data:
        old = {k: v for k, v in data.items() if isinstance(v, str)}
        videos = {}
        for name, status in old.items():
            videos[name] = {"status": status, "processed": "unknown", "api_calls": 0}
        data = {"videos": videos, "quota": {}, "last_run": None}
        save_progress(data)

    data.setdefault("quota", {})
    data.setdefault("videos", {})
    data.setdefault("last_run", None)
    return data


PROGRESS_TMP = PROGRESS_FILE.with_name(PROGRESS_FILE.name + ".tmp")


def save_progress(progress: dict):
    """原子写入进度文件（写 tmp → rename，崩溃不丢已有数据）。"""
    with _progress_lock:
        with open(PROGRESS_TMP, "w", encoding="utf-8") as f:
            json.dump(progress, f, ensure_ascii=False, indent=2)
        PROGRESS_TMP.replace(PROGRESS_FILE)  # 同文件系统 rename，原子操作


def discover_videos() -> dict[str, Path]:
    """扫描 VIDEOS_DIR 中的视频文件（非递归），返回 {视频名: 路径}。"""
    videos: dict[str, Path] = {}
    for ext in ("*.mp4", "*.webm", "*.m4v", "*.mov", "*.avi", "*.mkv", "*.mpeg"):
        for p in VIDEOS_DIR.glob(ext):
            if p.is_file():
                videos[p.stem] = p
    return dict(sorted(videos.items()))


def print_status(progress: dict, videos: dict):
    """打印任务进度摘要——这是 Claude Code 下一轮对话的唯一上下文入口。"""
    today = date.today().isoformat()
    quota = progress["quota"].get(today, {"used": 0, "limit": DAILY_QUOTA_LIMIT})
    used_today = quota["used"]
    limit_today = quota["limit"]

    done = sum(1 for v in progress["videos"].values() if v.get("status") == "done")
    failed = sum(1 for v in progress["videos"].values() if v.get("status") == "failed")
    pending = {k: v for k, v in videos.items()
               if progress["videos"].get(k, {}).get("status") != "done"}
    total = len(videos)

    remaining_quota = limit_today - used_today
    batch_size = min(len(pending), max(0, remaining_quota))

    print("\n" + "━" * 50)
    print("  zhihuTTS 任务状态")
    print("━" * 50)
    print(f"  总视频: {total}  |  已完成: {done}  |  失败: {failed}  |  待处理: {len(pending)}")
    print(f"  今日配额: {used_today}/{limit_today}")
    last_run = progress.get("last_run", "")
    if last_run:
        print(f"  上次运行: {last_run[:19]}")
    if total > 0:
        pct = done / total * 100
        print(f"  总进度: {pct:.1f}%")
    if batch_size <= 0 and len(pending) > 0:
        print(f"\n  ⚠ 今日配额已用完，明天再继续。")
    elif len(pending) > 0:
        pending_names = list(pending.keys())[:8]
        print(f"\n  今日可处理: {batch_size}/{len(pending)} 个")
        print(f"  下一个: {', '.join(pending_names[:3])}")
        if len(pending_names) > 3:
            print(f"  后续: {', '.join(pending_names[3:])}")
        if len(pending) > 8:
            print(f"  ...及其他 {len(pending) - 8} 个")
    else:
        print(f"\n  ✓ 全部完成！")
    print("━" * 50 + "\n")


def _cache_paths(video_path: Path) -> dict[str, Path]:
    stem = video_path.stem
    return {
        "transcript": TRANSCRIPT_CACHE_DIR / f"{stem}.json",
        "keyframes": KEYFRAME_CACHE_DIR / stem,
        "manifest": KEYFRAME_CACHE_DIR / stem / "manifest.json",
        "payload": PAYLOAD_CACHE_DIR / f"{stem}.json",
    }


def _load_preprocess_cache(video_path: Path, video_label: str):
    paths = _cache_paths(video_path)
    if not paths["transcript"].exists() or not paths["manifest"].exists():
        return None

    try:
        with open(paths["transcript"], "r", encoding="utf-8") as f:
            transcript = json.load(f)
        with open(paths["manifest"], "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        tprint(f"[{video_label}] 预处理缓存不可用: {e}")
        return None

    frames = [paths["keyframes"] / name for name in manifest.get("frames", [])]
    if not frames or any(not p.exists() for p in frames):
        tprint(f"[{video_label}] 关键帧缓存缺失，重新预处理")
        return None

    tprint(f"[{video_label}] 命中预处理缓存: {len(frames)} 张关键帧")
    return manifest.get("events", []), frames, transcript


def _save_preprocess_cache(video_path: Path, events: list[dict],
                           kept_frames: list[Path], transcript: dict):
    paths = _cache_paths(video_path)
    paths["transcript"].parent.mkdir(parents=True, exist_ok=True)
    paths["keyframes"].mkdir(parents=True, exist_ok=True)

    cached_frames = []
    for frame in kept_frames:
        cached = paths["keyframes"] / frame.name
        if frame.resolve() != cached.resolve():
            shutil.copy2(frame, cached)
        cached_frames.append(cached.name)

    with open(paths["transcript"], "w", encoding="utf-8") as f:
        json.dump(transcript, f, ensure_ascii=False, indent=2)
    with open(paths["manifest"], "w", encoding="utf-8") as f:
        json.dump({"events": events, "frames": cached_frames}, f, ensure_ascii=False, indent=2)


def _save_payload_cache(video_path: Path, transcript_text: str,
                        events: list[dict], kept_frames: list[Path]):
    paths = _cache_paths(video_path)
    paths["payload"].parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "video_name": video_path.stem,
        "transcript_text": transcript_text,
        "frames": [
            {"path": str(fp), "marker": frame_marker(fp, events)}
            for fp in kept_frames
        ],
        "events": events,
    }
    with open(paths["payload"], "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _write_run_report(started_at: datetime, ended_at: datetime, results: list[dict],
                      daily: dict, next_action: str):
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = RUNS_DIR / f"{started_at.date().isoformat()}.md"
    success = sum(1 for r in results if r.get("success"))
    failed = len(results) - success
    disk = shutil.disk_usage(Path(__file__).parent)

    lines = [
        f"# Run Report {started_at.date().isoformat()}",
        "",
        f"- Start: {started_at.isoformat(timespec='seconds')}",
        f"- End: {ended_at.isoformat(timespec='seconds')}",
        f"- Processed videos: {len(results)}",
        f"- Success: {success}",
        f"- Failed: {failed}",
        f"- Gemini calls: {sum(r.get('gemini_calls', 0) for r in results)}",
        f"- Quota after run: {daily.get('used', 0)}/{daily.get('limit', DAILY_QUOTA_LIMIT)}",
        f"- Disk free: {disk.free // (1024 ** 3)} GB",
        f"- Next recommended action: {next_action}",
        "",
        "| Video | Success | Failed stage | Backend | Fallback | Gemini calls |",
        "|---|---:|---|---|---|---:|",
    ]
    for result in results:
        lines.append(
            "| {video} | {success} | {stage} | {backend} | {fallback} | {calls} |".format(
                video=result.get("video", ""),
                success="yes" if result.get("success") else "no",
                stage=result.get("failed_stage") or "",
                backend=result.get("backend_used") or "",
                fallback=(result.get("fallback_reason") or "").replace("|", "/"),
                calls=result.get("gemini_calls", 0),
            )
        )

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    tprint(f"运行报告已保存: {report_path}")


def process_video(client, video_path: Path, output_path: Path, video_label: str) -> dict:
    """本地预处理（帧提取+转录）+ 单次 Gemini API 调用 + 写入 Markdown。"""
    result = {
        "video": video_path.stem,
        "success": False,
        "failed_stage": None,
        "gemini_calls": 0,
        "backend_used": None,
        "fallback_reason": None,
    }

    # ── Phase 1: Local preprocessing ──
    try:
        cached = _load_preprocess_cache(video_path, video_label)
        if cached:
            events, kept_frames, transcript = cached
        else:
            tprint(f"[{video_label}] 提取关键帧 & 转录音频...")
            events, kept_frames = extract_keyframes(video_path)
            transcript = transcribe_audio(video_path)
            _save_preprocess_cache(video_path, events, kept_frames, transcript)

        result["backend_used"] = transcript.get("backend_used")
        result["fallback_reason"] = transcript.get("fallback_reason")
        transcript_text = transcript_to_text(transcript)
    except Exception as e:
        tprint(f"[{video_label}] 预处理失败: {e}", level="error")
        result["failed_stage"] = "preprocess"
        return result

    slide_count = sum(1 for e in events if e["type"] == "slide")
    annot_count = sum(1 for e in events if e["type"] == "annotation")
    tprint(f"[{video_label}] 预处理完成: {slide_count} 次幻灯片, "
           f"{annot_count} 次标注, {len(kept_frames)} 张关键帧, "
           f"{len(transcript_text)} 字符逐字稿")

    # ── Phase 2: Build Gemini input ──
    _save_payload_cache(video_path, transcript_text, events, kept_frames)
    parts = [PROMPT_TEXT, transcript_text]
    for fp in kept_frames:
        parts.append(frame_marker(fp, events))
        parts.append(types.Part(
            inline_data=types.Blob(mime_type="image/jpeg", data=fp.read_bytes())
        ))

    # ── Phase 3: Gemini API call with retry ──
    gemini_result = _call_gemini_with_retry(client, parts, video_label)
    full_text = gemini_result["text"]
    result["gemini_calls"] = gemini_result["gemini_calls"]
    if full_text is None:
        result["failed_stage"] = "gemini"
        return result

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"# {video_path.stem}\n\n")
        f.write(full_text)

    tprint(f"[{video_label}] 完成，已保存至: {output_path.name}")
    result["success"] = True
    return result


def main():
    import sys
    sys.stdout.reconfigure(encoding="utf-8")  # Windows GBK → UTF-8

    parser = argparse.ArgumentParser(description="zhihuTTS 视频转 Markdown 知识库")
    parser.add_argument("--status", "--todo", action="store_true",
                        help="仅打印任务状态摘要（不执行处理）")
    args = parser.parse_args()

    _setup_logging()
    _logger.info("=" * 60 + " 任务开始")

    videos = discover_videos()
    if not videos:
        print(f"在 {VIDEOS_DIR} 下没有找到视频文件。")
        return

    progress = load_progress()
    print_status(progress, videos)

    if args.status:
        return

    api_key = os.environ.get("OPENCLAW_GOOGLE_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "未找到 OPENCLAW_GOOGLE_API_KEY 环境变量。\n"
            "请设置环境变量后再运行:\n"
            "  macOS/Linux:  export OPENCLAW_GOOGLE_API_KEY=your_key\n"
            "  Windows CMD:  set OPENCLAW_GOOGLE_API_KEY=your_key\n"
            "  Windows PS:   $env:OPENCLAW_GOOGLE_API_KEY=\"your_key\""
        )

    pending = {}
    for k, v in videos.items():
        entry = progress["videos"].get(k, {})
        if entry.get("status") == "done":
            # 兼容历史输出格式：当前是 TTS_MMDD_<stem>.md，过去可能直接 <stem>.md
            if not any(MARKDOWNS_DIR.glob(f"*{k}.md")):
                tprint(f"  ⚠ {k} 标记完成但 .md 文件缺失（可能被人为删除），重新处理")
                progress["videos"].pop(k, None)
                pending[k] = v
        else:
            pending[k] = v
    if not pending:
        print("所有视频已处理完毕！\n")
        return

    # ── 检查今日配额 ──
    today = date.today().isoformat()
    daily = progress["quota"].setdefault(today, {"used": 0, "limit": DAILY_QUOTA_LIMIT})
    remaining_quota = daily["limit"] - daily["used"]

    if remaining_quota <= 0:
        print(f"今日配额已用完 ({daily['used']}/{daily['limit']})，明天再来。\n")
        return

    batch = dict(list(pending.items())[:remaining_quota])
    if len(batch) < len(pending):
        print(f"今日剩余配额 {remaining_quota}，先处理 {len(batch)}/{len(pending)} 个。\n")

    # ── 防休眠（跨平台） ──
    caffeinate = None
    try:
        caffeinate = subprocess.Popen(["caffeinate", "-i"])
    except FileNotFoundError:
        pass  # Windows / Linux
    if caffeinate:
        print("  [防休眠] caffeinate 已启动。\n")
    else:
        print("  [防休眠] 跳过（当前系统不支持 caffeinate）\n")

    try:
        run_started_at = datetime.now()
        run_results = []
        base_url = os.environ.get("GEMINI_BASE_URL", "")
        http_opts = types.HttpOptions(
            timeout=3600000,
            base_url=base_url or None,
            api_version=os.environ.get("GEMINI_API_VERSION", "v1beta") if base_url else None,
        )
        client = genai.Client(api_key=api_key, http_options=http_opts)
        MARKDOWNS_DIR.mkdir(exist_ok=True)

        total_batch = len(batch)
        for i, (video_stem, video_path) in enumerate(batch.items(), 1):
            date_prefix = date.today().strftime("%m%d")
            output_path = MARKDOWNS_DIR / (f"TTS_{date_prefix}_" + video_stem + ".md")
            video_label = f"{i}/{total_batch} {video_stem[:30]}"

            result = process_video(client, video_path, output_path, video_label)
            success = result["success"]
            run_results.append(result)

            if success:
                kf_dir = KEYFRAMES_DIR / video_stem
                if kf_dir.exists():
                    shutil.rmtree(kf_dir)
                    tprint(f"  [{video_label}] 已清理关键帧缓存")

            # 更新进度
            progress["videos"][video_stem] = {
                "status": "done" if success else "failed",
                "processed": today,
                "api_calls": (
                    progress["videos"].get(video_stem, {}).get("api_calls", 0)
                    + result.get("gemini_calls", 0)
                ),
                "failed_stage": result.get("failed_stage"),
                "backend_used": result.get("backend_used"),
                "fallback_reason": result.get("fallback_reason"),
            }
            daily["used"] += result.get("gemini_calls", 0)
            progress["last_run"] = datetime.now().isoformat()
            save_progress(progress)

            # 重新打印状态摘要
            print_status(progress, videos)

        total_done = sum(1 for v in progress["videos"].values() if v.get("status") == "done")
        total_failed = sum(1 for v in progress["videos"].values() if v.get("status") == "failed")
        next_action = "全部完成" if total_done == len(videos) else "继续处理剩余视频或重试 failed_stage=gemini 的任务"
        _write_run_report(run_started_at, datetime.now(), run_results, daily, next_action)
        print(f"\n本轮完成。累计成功: {total_done}，失败: {total_failed}")

    finally:
        if caffeinate:
            caffeinate.terminate()
            print("  [防休眠] caffeinate 已关闭。\n")


if __name__ == "__main__":
    main()
