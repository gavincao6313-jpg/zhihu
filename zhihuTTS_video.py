"""
zhihuTTS_video.py — 视频预处理流水线

本地 ffmpeg → 帧提取/场景检测
本地 faster-whisper → 逐字稿
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

def _transcribe_cpu(wav_path: Path, model_size: str = "small",
                     language: str = "zh") -> dict:
    """用 faster-whisper（CPU）转写音频。"""
    from faster_whisper import WhisperModel

    device = os.environ.get("WHISPER_DEVICE", "cpu")
    cpu_threads = int(os.environ.get("WHISPER_CPU_THREADS", "0"))
    num_workers = int(os.environ.get("WHISPER_CPU_WORKERS", "4"))
    print(f"  [CPU] 加载 Whisper {model_size} (threads={cpu_threads or 'auto'}, workers={num_workers})...")
    model = WhisperModel(model_size, device=device,
                         compute_type="int8", cpu_threads=cpu_threads,
                         num_workers=num_workers)
    segments, info = model.transcribe(str(wav_path), language=language,
                                       beam_size=5, word_timestamps=True)
    print(f"  [CPU] 检测到语言: {info.language} (概率 {info.language_probability:.2f})")
    return _collect_segments(segments)


def _transcribe_vulkan(wav_path: Path, model_size: str = "small",
                        language: str = "zh") -> dict:
    """用 whisper-cpp-python（Vulkan / AMD GPU）转写音频。"""
    try:
        from whisper_cpp_python import Whisper
    except ImportError:
        raise ImportError(
            "Vulkan 后端需要 whisper-cpp-python（带 Vulkan 编译）:\n"
            "  CMAKE_ARGS='-DWHISPER_VULKAN=ON' pip install whisper-cpp-python\n"
            "或回退: 设置 WHISPER_BACKEND=cpu 使用 faster-whisper"
        )

    print(f"  [Vulkan] 加载 Whisper {model_size}...", flush=True)
    try:
        model = Whisper.from_pretrained(model_size)
    except Exception as e:
        raise RuntimeError(
            f"[Vulkan] 模型 {model_size} 下载/加载失败: {e}\n"
            "检查网络连接，或设置 WHISPER_BACKEND=cpu 回退 faster-whisper"
        )
    print(f"  [Vulkan] 转写中...", flush=True)
    raw = model.transcribe(str(wav_path), language=language)

    if isinstance(raw, dict):
        raw_segments = raw.get("segments") or []
    elif hasattr(raw, "segments"):
        raw_segments = raw.segments
    elif isinstance(raw, list):
        raw_segments = raw
    else:
        raw_segments = []

    segments = []
    for seg in raw_segments:
        if isinstance(seg, dict):
            segments.append({
                "start": seg.get("start", 0.0),
                "end": seg.get("end", 0.0),
                "text": seg.get("text", "").strip(),
                "words": seg.get("words", []),
            })
        else:
            segments.append({
                "start": getattr(seg, "start", 0.0),
                "end": getattr(seg, "end", 0.0),
                "text": getattr(seg, "text", "").strip(),
                "words": getattr(seg, "words", []),
            })
    print(f"  [Vulkan] 转写完成: {len(segments)} 个片段", flush=True)
    return {"segments": segments}


def _collect_segments(generator) -> dict:
    """将 faster-whisper 的 segment generator 落实为 dict。"""
    segments = []
    for seg in generator:
        words = []
        if seg.words:
            words = [{"word": w.word, "start": w.start, "end": w.end}
                     for w in seg.words]
        segments.append({
            "start": seg.start, "end": seg.end,
            "text": seg.text.strip(),
            "words": words,
        })
    return {"segments": segments}


def transcribe_audio(video_path: Path, model_size: str = "small",
                     language: str = "zh") -> dict:
    """转写音频，自动选择后端（WHISPER_BACKEND 环境变量）。"""
    with tempfile.NamedTemporaryFile(suffix=".wav", prefix="zhihu_", delete=False) as f:
        wav_path = Path(f.name)
    try:
        print(f"  提取音频: {video_path.name} → 16kHz mono WAV...")
        subprocess.run([
            "ffmpeg", "-i", str(video_path),
            "-vn", "-acodec", "pcm_s16le",
            "-ar", "16000", "-ac", "1",
            "-y", str(wav_path),
        ], capture_output=True, check=True, timeout=FFMPEG_TIMEOUT)

        backend = os.environ.get("WHISPER_BACKEND", "auto")
        if backend in ("vulkan", "auto"):
            try:
                return _transcribe_vulkan(wav_path, model_size, language)
            except (ImportError, RuntimeError) as e:
                if backend == "vulkan":
                    raise
                print(f"  [Vulkan] 不可用 ({e})，回退到 CPU...")

        return _transcribe_cpu(wav_path, model_size, language)
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
        frame_info.append({"path": str(fp), "timestamp_s": ts})

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
