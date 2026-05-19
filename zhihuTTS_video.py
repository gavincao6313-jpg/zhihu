"""
zhihuTTS_video.py — 视频预处理流水线

本地 ffmpeg → 帧提取/场景检测
本地 FunASR/SenseVoice 或 faster-whisper → 逐字稿
→ 结构化输入包，供 Gemini API 组装

用法:
    from zhihuTTS_video import extract_keyframes, transcribe_audio, build_gemini_payload
    events, kept_frames = extract_keyframes(video_path)
    transcript = transcribe_audio(video_path)
    payload = build_gemini_payload(video_path.stem, transcript, events, kept_frames)
"""

import json
import os
import platform
import re
import subprocess
import tempfile
import shutil
import time
from pathlib import Path

import numpy as np
from PIL import Image


# ── 配置 ────────────────────────────────────────────

FRAME_SCALE = 320          # 帧缩略图宽度，兼顾速度与精度
FRAME_FPS = 1              # 采样帧率
SLIDE_THRESHOLD = 0.3      # 幻灯片切换判定
ANNOT_THRESHOLD = 0.02     # 画笔标注判定
MERGE_WINDOW = 3           # 相邻变化事件合并窗口（单位：帧）
FFMPEG_TIMEOUT = 7200      # ffmpeg 超时（秒），大视频可能需要更长时间
KEYFRAMES_DIR = Path(__file__).parent / "Videos" / "keyframes"  # 关键帧输出目录
TMP_DIR = Path(__file__).parent / "Videos" / ".tmp"

DEFAULT_TRANSCRIBE_BACKEND = "sensevoice"
SENSEVOICE_MODEL = os.environ.get("SENSEVOICE_MODEL", "iic/SenseVoiceSmall")
SENSEVOICE_VAD_MODEL = os.environ.get("SENSEVOICE_VAD_MODEL", "fsmn-vad")

GLOSSARY_PATTERNS = [
    (r"\bapi\b", "API"),
    (r"\bmcp\b", "MCP"),
    (r"\bcli\b", "CLI"),
    (r"\brag\b", "RAG"),
    (r"\bweb\s+coding\b", "web coding"),
    (r"\bai\s+coding\b", "AI coding"),
    (r"\bmini\s*max\s*agent\b", "MiniMax Agent"),
    (r"\bcloud\s+code\b", "Claude Code"),
    (r"\bcloud\s+coldword\b", "Claude Code"),
    (r"克拉\s*code", "Claude Code"),
    (r"叉\s*code", "Cursor"),
]


# ── 关键帧提取 + 场景检测 ────────────────────────────

def _extract_frames(video_path: Path, fps: float = FRAME_FPS,
                    scale: int = FRAME_SCALE) -> list[Path]:
    """用 ffmpeg 按固定帧率提取缩略图到 KEYFRAMES_DIR/<video_stem>/，返回帧文件列表。"""
    out_dir = KEYFRAMES_DIR / video_path.stem
    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
        if out_dir.exists() and platform.system() == "Windows":
            subprocess.run(["cmd", "/c", "rmdir", "/s", "/q",
                           str(out_dir.resolve())], capture_output=True)
        if out_dir.exists():
            shutil.rmtree(out_dir)  # 最后尝试，不忽略错误
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir.resolve() / "frame_%05d.jpg")
    cmd = ["ffmpeg",
        "-i", str(video_path.resolve()),
        "-vf", f"fps={fps},scale={scale}:-1",
        "-q:v", "5",
        "-y", pattern,
    ]
    subprocess.run(cmd, capture_output=True, check=True, timeout=FFMPEG_TIMEOUT)

    frames = sorted(out_dir.glob("frame_*.jpg"),
                    key=lambda p: int(re.search(r"frame_(\d+)", p.stem).group(1)))
    return frames


def analyze_frames(frames: list[Path]) -> tuple[list[dict], list[Path]]:
    """
    逐帧比较，返回：
      1. events — 检测事件列表 [{"type": "slide"|"annotation",
                                  "frame_idx": int, "diff": float}, ...]
      2. kept_frames — 保留的帧文件列表（含标注前/后帧对）
    """
    if not frames:
        return [], []

    def _diff(a_path, b_path):
        a = np.array(Image.open(a_path).convert("L"), dtype=np.float32)
        b = np.array(Image.open(b_path).convert("L"), dtype=np.float32)
        return float(np.mean(np.abs(a - b)) / 255.0)

    raw_events = []
    for i in range(1, len(frames)):
        diff = _diff(frames[i - 1], frames[i])
        if diff >= SLIDE_THRESHOLD:
            raw_events.append((i, "slide", diff))
        elif diff >= ANNOT_THRESHOLD:
            raw_events.append((i, "annotation", diff))

    # 合并相邻同类型事件（幻灯片合并取突变最大帧，标注合并取最后状态帧 + 记录首帧索引）
    merged = []
    for i, etype, diff in raw_events:
        if merged and merged[-1]["type"] == etype and i - merged[-1]["frame_idx"] <= MERGE_WINDOW:
            if etype == "slide" and diff > merged[-1]["diff"]:
                merged[-1].update(frame_idx=i, diff=round(diff, 4))
            elif etype == "annotation":
                merged[-1].update(frame_idx=i, diff=round(max(diff, merged[-1]["diff"]), 4))
        else:
            merged.append({"type": etype, "frame_idx": i, "first_idx": i, "diff": round(diff, 4)})

    events = []
    kept = {0}  # 第一帧总是保留
    for ev in merged:
        events.append({"type": ev["type"], "frame_idx": ev["frame_idx"], "diff": ev["diff"]})
        kept.add(ev["frame_idx"])
        if ev["type"] == "annotation":
            kept.add(ev["first_idx"] - 1)  # 标注序列起始帧的前一帧（"标注前"状态）

    kept_frames = [frames[i] for i in sorted(kept)]
    return events, kept_frames


def extract_keyframes(video_path: Path) -> tuple[list[dict], list[Path]]:
    """
    完整流程：提取帧 → 分析变化 → 返回 (events, kept_frames)。
    events 供上游了解帧含义，kept_frames 供 Gemini 视觉输入。
    """
    print(f"  提取帧: {video_path.name} ({FRAME_FPS}fps, scale={FRAME_SCALE})...")
    frames = _extract_frames(video_path)
    print(f"  分析 {len(frames)} 帧...")
    events, kept = analyze_frames(frames)
    print(f"  检测: {sum(1 for e in events if e['type']=='slide')} 次幻灯片切换, "
          f"{sum(1 for e in events if e['type']=='annotation')} 次标注事件")
    ratio = len(kept) / max(len(frames), 1) * 100
    print(f"  保留 {len(kept)}/{len(frames)} 帧 ({ratio:.1f}%)")
    return events, kept


# ── 音频转录 ────────────────────────────────────────

def _normalize_transcribe_backend(value: str) -> str:
    backend = (value or DEFAULT_TRANSCRIBE_BACKEND).strip().lower()
    aliases = {
        "funasr": "sensevoice",
        "sensevoice-small": "sensevoice",
        "faster-whisper": "cpu",
        "faster_whisper": "cpu",
        "whisper": "cpu",
        "vulkan": "whispercpp-vulkan",
    }
    return aliases.get(backend, backend)


def requested_transcribe_backend() -> str:
    """Return the requested ASR backend."""
    return _normalize_transcribe_backend(
        os.environ.get("TRANSCRIBE_BACKEND", DEFAULT_TRANSCRIBE_BACKEND)
    )


def _normalize_transcript_text(text: str) -> str:
    """Normalize recurring ASR spellings for project-domain terms."""
    normalized = str(text or "").strip()
    for pattern, replacement in GLOSSARY_PATTERNS:
        normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
    return normalized

def _transcribe_cpu(wav_path: Path, model_size: str = "small",
                     language: str = "zh") -> dict:
    """用 faster-whisper（CPU）转写音频。"""
    from faster_whisper import WhisperModel

    device = os.environ.get("WHISPER_DEVICE", "cpu")
    cpu_threads = int(os.environ.get("WHISPER_CPU_THREADS", "0"))
    num_workers = int(os.environ.get("WHISPER_CPU_WORKERS", "4"))
    beam_size = int(os.environ.get("WHISPER_BEAM_SIZE", "1"))
    word_timestamps = os.environ.get("WHISPER_WORD_TIMESTAMPS", "0") == "1"
    print(
        f"  [CPU] 加载 Whisper {model_size} "
        f"(threads={cpu_threads or 'auto'}, workers={num_workers}, "
        f"beam={beam_size}, word_ts={int(word_timestamps)})..."
    )
    model = WhisperModel(model_size, device=device,
                         compute_type="int8", cpu_threads=cpu_threads,
                         num_workers=num_workers)
    segments, info = model.transcribe(str(wav_path), language=language,
                                       beam_size=beam_size,
                                       word_timestamps=word_timestamps)
    print(f"  [CPU] 检测到语言: {info.language} (概率 {info.language_probability:.2f})")
    return _collect_segments(segments, include_words=word_timestamps)


def _audio_duration_s(wav_path: Path) -> float:
    completed = subprocess.run(
        [
            "ffprobe",
            "-hide_banner",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(wav_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=FFMPEG_TIMEOUT,
    )
    try:
        return max(0.0, float(completed.stdout.strip()))
    except ValueError:
        return 0.0


def _funasr_time_to_seconds(value, duration_s: float) -> float:
    if value is None:
        return 0.0
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return 0.0
    if seconds > duration_s + 5:
        seconds /= 1000.0
    return max(0.0, seconds)


def _sensevoice_segments(result: list[dict], duration_s: float) -> list[dict]:
    from funasr.utils.postprocess_utils import rich_transcription_postprocess

    segments = []
    fallback_start = 0.0
    for item in result:
        sentence_info = item.get("sentence_info") if isinstance(item, dict) else None
        if isinstance(sentence_info, list) and sentence_info:
            for sentence in sentence_info:
                text = _normalize_transcript_text(
                    rich_transcription_postprocess(str(sentence.get("text", "")))
                )
                if not text:
                    continue
                start = _funasr_time_to_seconds(sentence.get("start"), duration_s)
                end = _funasr_time_to_seconds(sentence.get("end"), duration_s)
                if end <= start:
                    end = start
                segments.append({"start": start, "end": end, "text": text, "words": []})
            continue

        raw_text = str(item.get("text", "")) if isinstance(item, dict) else str(item)
        text = _normalize_transcript_text(rich_transcription_postprocess(raw_text))
        if not text:
            continue

        timestamps = item.get("timestamp") if isinstance(item, dict) else None
        start = fallback_start
        end = duration_s
        if isinstance(timestamps, list) and timestamps:
            pairs = [ts for ts in timestamps if isinstance(ts, (list, tuple)) and len(ts) >= 2]
            if pairs:
                start = _funasr_time_to_seconds(pairs[0][0], duration_s)
                end = _funasr_time_to_seconds(pairs[-1][1], duration_s)
        if end <= start:
            end = duration_s if duration_s > start else start
        segments.append({"start": start, "end": end, "text": text, "words": []})
        fallback_start = end

    if not segments:
        return []
    return sorted(segments, key=lambda seg: (seg["start"], seg["end"]))


def _transcribe_sensevoice(wav_path: Path, language: str = "zh") -> dict:
    """用 FunASR SenseVoice 转写音频，并适配为现有 transcript shape。"""
    try:
        from funasr import AutoModel
    except ImportError as e:
        raise RuntimeError(
            "FUNASR/SenseVoice 未安装。请先安装 funasr、modelscope、torch、torchaudio。"
        ) from e

    device = os.environ.get("SENSEVOICE_DEVICE", "cpu")
    batch_size_s = int(os.environ.get("SENSEVOICE_BATCH_SIZE_S", "60"))
    # merge_vad=False preserves VAD segment boundaries → sentence_info timestamps are accurate.
    # Set SENSEVOICE_MERGE_VAD=true only for short clips where text coherence matters more than precision.
    merge_vad = os.environ.get("SENSEVOICE_MERGE_VAD", "false").lower() in ("1", "true", "yes")
    merge_length_s = int(os.environ.get("SENSEVOICE_MERGE_LENGTH_S", "15"))
    print(
        f"  [SenseVoice] 加载 {SENSEVOICE_MODEL} "
        f"(vad={SENSEVOICE_VAD_MODEL}, device={device}, merge_vad={merge_vad})..."
    )
    model = AutoModel(
        model=SENSEVOICE_MODEL,
        vad_model=SENSEVOICE_VAD_MODEL,
        device=device,
        disable_update=True,
    )
    _gen_kwargs: dict = dict(
        input=str(wav_path),
        cache={},
        language=language,
        use_itn=True,
        batch_size_s=batch_size_s,
        merge_vad=merge_vad,
    )
    if merge_vad:
        _gen_kwargs["merge_length_s"] = merge_length_s
    result = model.generate(**_gen_kwargs)
    duration_s = _audio_duration_s(wav_path)
    segments = _sensevoice_segments(result, duration_s)
    if not segments:
        print("  [SenseVoice] 无语音，跳过此切片", flush=True)
        return {
            "segments": [],
            "sensevoice": {
                "model": SENSEVOICE_MODEL,
                "vad_model": SENSEVOICE_VAD_MODEL,
                "device": device,
                "duration_s": duration_s,
            },
        }
    print(f"  [SenseVoice] 转写完成: {len(segments)} 个片段", flush=True)
    return {
        "segments": segments,
        "sensevoice": {
            "model": SENSEVOICE_MODEL,
            "vad_model": SENSEVOICE_VAD_MODEL,
            "device": device,
            "duration_s": duration_s,
        },
    }


def _timestamp_to_seconds(value) -> float:
    """解析 whisper.cpp JSON 中的秒数或时间戳字符串。"""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return 0.0
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return float(text)

    text = text.replace(",", ".")
    parts = text.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
    except ValueError:
        return 0.0
    return 0.0


def _parse_whispercpp_json(data: dict) -> dict:
    """将 whisper.cpp CLI JSON 转为当前 transcript shape。"""
    raw_segments = data.get("segments") or data.get("transcription") or []
    segments = []

    for seg in raw_segments:
        if not isinstance(seg, dict):
            continue

        timestamps = seg.get("timestamps") or {}
        start = seg.get("start", timestamps.get("from"))
        end = seg.get("end", timestamps.get("to"))
        segments.append({
            "start": _timestamp_to_seconds(start),
            "end": _timestamp_to_seconds(end),
            "text": _normalize_transcript_text(seg.get("text", "")),
            "words": [],
        })

    if not segments and data.get("text"):
        segments.append({
            "start": 0.0,
            "end": 0.0,
            "text": _normalize_transcript_text(data["text"]),
            "words": [],
        })

    return {"segments": segments}


def _transcribe_whispercpp_cli(wav_path: Path, model_size: str = "small",
                               language: str = "zh") -> dict:
    """用外部 whisper.cpp CLI 转写音频。"""
    exe = os.environ.get("WHISPER_CPP_EXE", "").strip()
    model = os.environ.get("WHISPER_CPP_MODEL", "").strip()
    if not exe or not model:
        raise RuntimeError("WHISPER_CPP_EXE 和 WHISPER_CPP_MODEL 必须同时配置")

    exe_path = Path(exe)
    model_path = Path(model)
    if not exe_path.exists():
        raise RuntimeError(f"WHISPER_CPP_EXE 不存在: {exe_path}")
    if not model_path.exists():
        raise RuntimeError(f"WHISPER_CPP_MODEL 不存在: {model_path}")

    out_prefix = wav_path.with_suffix("")
    out_json = out_prefix.with_suffix(".json")
    out_json.unlink(missing_ok=True)

    cmd = [
        str(exe_path),
        "-m", str(model_path),
        "-f", str(wav_path),
        "-l", language,
        "-oj",
        "-of", str(out_prefix),
    ]
    print(f"  [whisper.cpp] 转写中: {exe_path.name}", flush=True)
    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=FFMPEG_TIMEOUT,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "whisper.cpp CLI 转写失败 "
            f"(exit={completed.returncode}): {completed.stderr.strip() or completed.stdout.strip()}"
        )
    if not out_json.exists():
        raise RuntimeError(f"whisper.cpp CLI 未生成 JSON: {out_json}")

    with open(out_json, "r", encoding="utf-8") as f:
        transcript = _parse_whispercpp_json(json.load(f))
    out_json.unlink(missing_ok=True)
    print(f"  [whisper.cpp] 转写完成: {len(transcript['segments'])} 个片段", flush=True)
    return transcript


def _collect_segments(generator, include_words: bool = False) -> dict:
    """将 faster-whisper 的 segment generator 落实为 dict。"""
    segments = []
    for seg in generator:
        words = []
        if include_words and seg.words:
            words = [{"word": w.word, "start": w.start, "end": w.end}
                     for w in seg.words]
        segments.append({
            "start": seg.start, "end": seg.end,
            "text": _normalize_transcript_text(seg.text),
            "words": words,
        })
    return {"segments": segments}


def transcribe_audio(video_path: Path, model_size: str = "small",
                     language: str = "zh") -> dict:
    """转写音频，默认使用 FunASR/SenseVoice，可通过 TRANSCRIBE_BACKEND 切换。"""
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=TMP_DIR, suffix=".wav", prefix="zhihu_", delete=False) as f:
        wav_path = Path(f.name)
    backend = requested_transcribe_backend()
    fallback_reason = None
    started_at = time.monotonic()

    try:
        print(f"  提取音频: {video_path.name} → 16kHz mono WAV...")
        subprocess.run([
            "ffmpeg", "-i", str(video_path),
            "-vn", "-acodec", "pcm_s16le",
            "-ar", "16000", "-ac", "1",
            "-y", str(wav_path),
        ], capture_output=True, check=True, timeout=FFMPEG_TIMEOUT)

        if backend == "sensevoice":
            transcript = _transcribe_sensevoice(wav_path, language)
            transcript["backend_used"] = "sensevoice"
            transcript["fallback_reason"] = None
            transcript["duration_s"] = round(time.monotonic() - started_at, 2)
            print(f"  转写后端: sensevoice, 用时 {transcript['duration_s']}s")
            return transcript

        if backend in ("auto", "whispercpp-vulkan", "whispercpp"):
            cli_configured = bool(os.environ.get("WHISPER_CPP_EXE") and os.environ.get("WHISPER_CPP_MODEL"))
            if backend != "auto" or cli_configured:
                try:
                    transcript = _transcribe_whispercpp_cli(wav_path, model_size, language)
                    backend_used = "whispercpp-vulkan"
                except Exception as e:
                    if backend != "auto":
                        raise
                    fallback_reason = str(e)
                    print(f"  [whisper.cpp] 不可用 ({fallback_reason})，回退到 CPU...")
                else:
                    transcript["backend_used"] = backend_used
                    transcript["fallback_reason"] = fallback_reason
                    transcript["duration_s"] = round(time.monotonic() - started_at, 2)
                    print(f"  转写后端: {backend_used}, 用时 {transcript['duration_s']}s")
                    return transcript

        if backend not in ("auto", "cpu", "whispercpp-vulkan", "whispercpp"):
            raise ValueError(f"不支持的 TRANSCRIBE_BACKEND: {backend}")

        transcript = _transcribe_cpu(wav_path, model_size, language)
        transcript["backend_used"] = "cpu"
        transcript["fallback_reason"] = fallback_reason
        transcript["duration_s"] = round(time.monotonic() - started_at, 2)
        print(f"  转写后端: cpu, 用时 {transcript['duration_s']}s")
        if fallback_reason:
            print(f"  CPU fallback reason: {fallback_reason}")
        return transcript
    finally:
        wav_path.unlink(missing_ok=True)


def transcript_to_text(transcript: dict) -> str:
    """将 whisper 转写结果合并为纯文本（带时间戳段落）。"""
    lines = []
    for seg in transcript["segments"]:
        ts = f"[{_fmt_ts(seg['start'])} - {_fmt_ts(seg['end'])}]"
        lines.append(f"{ts} {seg['text']}")
    return "\n".join(lines)


def _fmt_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def frame_marker(frame_path: Path, events: list[dict]) -> str:
    """生成 Gemini 图片前置元数据标记。"""
    match = re.search(r"frame_(\d+)", frame_path.stem)
    timestamp_s = int(match.group(1)) if match else 0
    # ffmpeg %05d filenames are 1-based; events use 0-based frame_idx.
    # Slide/annotation "last" frames: filename N+1 → frame_idx N (try ts-1 first).
    # Annotation "before" frames: filename N → frame_idx N (fallback to ts).
    event = next((e for e in events if e.get("frame_idx") == timestamp_s - 1), None)
    if event is None:
        event = next((e for e in events if e.get("frame_idx") == timestamp_s), None)
    if event:
        return (
            f"Frame [{_fmt_ts(timestamp_s)}] "
            f"type={event.get('type', 'context')} diff={event.get('diff', 0)}"
        )
    return f"Frame [{_fmt_ts(timestamp_s)}] type=context diff=0"


# ── Gemini 输入包组装 ──────────────────────────────

def build_gemini_payload(video_name: str, transcript: dict,
                          events: list[dict], kept_frames: list[Path]) -> dict:
    """
    将逐字稿、关键帧、事件元信息组装为 Gemini 输入包。
    返回 dict，包含 full_text、frames（路径+时间戳）、events、stats。
    """
    full_text = transcript_to_text(transcript)
    slide_count = sum(1 for e in events if e["type"] == "slide")
    annot_count = sum(1 for e in events if e["type"] == "annotation")

    frame_info = []
    for fp in kept_frames:
        match = re.search(r"frame_(\d+)", fp.stem)
        ts = int(match.group(1)) if match else 0
        frame_info.append({
            "path": str(fp),
            "timestamp_s": ts,
            "marker": frame_marker(fp, events),
        })

    return {
        "video_name": video_name,
        "full_text": full_text,
        "frames": frame_info,
        "events": events,
        "stats": {
            "slide_changes": slide_count,
            "annotations": annot_count,
            "frames_total": len(kept_frames),
            "text_chars": len(full_text),
        },
    }


# ── CLI 测试入口 ────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="zhihuTTS 视频预处理流水线")
    parser.add_argument("video", help="输入视频文件路径")
    parser.add_argument("--frames-only", action="store_true",
                        help="仅执行帧提取+场景检测")
    parser.add_argument("--transcribe", action="store_true",
                        help="仅执行语音转文字")
    args = parser.parse_args()

    video_path = Path(args.video)
    if not video_path.exists():
        print(f"文件不存在: {video_path}")
        return

    if args.transcribe:
        transcript = transcribe_audio(video_path)
        print(f"\n=== 转写结果（前 5 段）===")
        for seg in transcript["segments"][:5]:
            print(f"[{_fmt_ts(seg['start'])}] {seg['text']}")
        return

    if args.frames_only:
        events, kept = extract_keyframes(video_path)
        print(f"\n=== 检测事件 ===")
        for e in events:
            ts = e["frame_idx"]
            print(f"  t={ts}s [{e['type']}] diff={e['diff']}")
        return

    print("=" * 50)
    print(f"处理: {video_path.name}")
    print("=" * 50)

    events, kept = extract_keyframes(video_path)
    transcript = transcribe_audio(video_path)
    payload = build_gemini_payload(video_path.stem, transcript, events, kept)

    print(f"\n=== Gemini 输入包摘要 ===")
    stats = payload["stats"]
    print(f"  视频: {payload['video_name']}")
    print(f"  幻灯片切换: {stats['slide_changes']} 次")
    print(f"  标注事件: {stats['annotations']} 次")
    print(f"  关键帧: {stats['frames_total']} 张")
    print(f"  逐字稿: {stats['text_chars']} 字符")

    out_path = video_path.with_suffix(".payload.json")
    ser = {
        "video_name": payload["video_name"],
        "full_text": payload["full_text"],
        "frames": [{"path": f["path"], "timestamp_s": f["timestamp_s"]}
                   for f in payload["frames"]],
        "events": payload["events"],
        "stats": payload["stats"],
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(ser, f, ensure_ascii=False, indent=2)
    print(f"\n  → 输入包已保存: {out_path}")


if __name__ == "__main__":
    main()
