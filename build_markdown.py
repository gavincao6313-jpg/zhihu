"""Build structured Markdown from replay transcript + keyframe events."""
import json, re
from pathlib import Path

# Load transcript
with open(r"D:\zhihu\zhihu_url\runs\replay-20260518.combined-transcript.txt", "r", encoding="utf-8") as f:
    raw_text = f.read()

# Load payload with events
with open(r"D:\zhihu\zhihu_url\runs\replay-20260518.payload.json", "r", encoding="utf-8") as f:
    payload = json.load(f)

events = payload.get("events", [])
total_duration = 10300.7  # seconds

print(f"Raw text: {len(raw_text)} chars")
print(f"Events: {len(events)}")

# Clean the text
text = raw_text.strip()
# Remove the timestamp prefix if present
text = re.sub(r'^\[00:00:00 - 02:51:40\]\s*', '', text)

# Split into sentences
# Chinese sentence endings
sentences = re.split(r'(?<=[。！？；\n])\s*', text)
sentences = [s.strip() for s in sentences if s.strip()]
print(f"Sentences: {len(sentences)}")

# Build event lookup: timestamp_seconds -> event
event_map = {}
for ev in events:
    ts = ev.get("frame_idx", 0)
    event_map[ts] = ev

# Create slide change markers for section headings
slide_times = sorted([e["frame_idx"] for e in events if e.get("type") == "slide"])
print(f"Slide changes: {len(slide_times)}")

# Estimate per-character timing
total_chars = sum(len(s) for s in sentences)
chars_per_second = total_chars / total_duration if total_duration > 0 else 1
print(f"Chars per second: {chars_per_second:.2f}")

def fmt_ts(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

# Build markdown
lines = []
lines.append("# 知乎直播回放转写文档")
lines.append("")
lines.append(f"**日期**: 2026-05-18")
lines.append(f"**时长**: {fmt_ts(int(total_duration))}")
lines.append(f"**转写引擎**: SenseVoiceSmall + FSMN-VAD")
lines.append(f"**转写方式**: 回放视频离线转写")
lines.append("")
lines.append("---")
lines.append("")

# Walk through sentences, inserting slide markers
char_pos = 0
current_slide = 0
slide_idx = 0
lines.append("## 00:00:00 — 开场")
lines.append("")

for sent in sentences:
    # Calculate approximate timestamp for this sentence
    approx_ts = char_pos / chars_per_second

    # Check if we crossed a slide boundary
    while slide_idx < len(slide_times) and slide_times[slide_idx] <= approx_ts:
        slide_ts = slide_times[slide_idx]
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(f"## {fmt_ts(slide_ts)} — 幻灯片切换")
        lines.append("")
        slide_idx += 1

    # Add sentence with timestamp
    lines.append(f"> [{fmt_ts(approx_ts)}] {sent}")
    char_pos += len(sent)

# If we have annotation events, add a summary section
annotation_count = sum(1 for e in events if e.get("type") == "annotation")
lines.append("")
lines.append("---")
lines.append("")
lines.append("## 转写统计")
lines.append("")
lines.append(f"- **总字符数**: {total_chars:,}")
lines.append(f"- **句子数**: {len(sentences):,}")
lines.append(f"- **幻灯片切换**: {len(slide_times)} 次")
lines.append(f"- **标注/画笔事件**: {annotation_count} 次")
lines.append(f"- **关键帧提取**: {payload.get('frames_count', 0)} 张")
lines.append("")

# Save
out_path = Path(r"D:\zhihu\zhihu_url\runs\replay-20260518.md")
with open(out_path, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"\nMarkdown saved: {out_path}")
print(f"Lines: {len(lines)}")
