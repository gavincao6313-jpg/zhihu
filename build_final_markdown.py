"""Build final structured Markdown from replay transcript.

Uses accurate per-segment timestamps from transcript.json (requires merge_vad=False run).
For each segment, sub-sentence timestamps are distributed proportionally within the
segment's [start, end] range — accurate to within one VAD segment (~2-5 seconds).
"""
import json, re
from pathlib import Path

RUNS_DIR = Path(r"D:\zhihu\zhihu_url\runs")
TRANSCRIPT_JSON = RUNS_DIR / "replay-20260518.transcript.json"
PAYLOAD_JSON    = RUNS_DIR / "replay-20260518.payload.json"
OUT_PATH        = RUNS_DIR / "replay-20260518-final.md"


def fmt_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def split_sentences(text: str) -> list[str]:
    parts = re.split(r'(?<=[。！？；])', text)
    return [s.strip() for s in parts if s.strip()]


# --- Load data ---
with open(TRANSCRIPT_JSON, encoding="utf-8") as f:
    transcript = json.load(f)

with open(PAYLOAD_JSON, encoding="utf-8") as f:
    payload = json.load(f)

segments = transcript["segments"]
events   = payload.get("events", [])

if not segments:
    raise SystemExit("transcript.json has no segments — re-run transcribe_replay.py with SENSEVOICE_MERGE_VAD=false")

total_duration   = segments[-1]["end"]
annotation_count = sum(1 for e in events if e.get("type") == "annotation")
slide_times      = sorted(e["frame_idx"] for e in events if e.get("type") == "slide")

# --- Expand segments → (timestamp_s, sentence) pairs ---
# Each segment has accurate VAD start/end; sub-sentences get proportional offsets within that window.
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

# --- Build markdown ---
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

slide_idx  = 0
section_num = 1
lines += [f"## 第 {section_num} 部分 — {fmt_ts(0)}", ""]

buf: list[str] = []
for ts, sent in stamped:
    # Advance past all slide boundaries that fall before this sentence
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
print(f"Written: {OUT_PATH}")
print(f"Sections: {section_num}  Sentences: {total_sentences}  VAD segments: {len(segments)}")
