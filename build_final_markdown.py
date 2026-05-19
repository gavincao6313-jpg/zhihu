"""Build final structured Markdown from replay transcript."""
import json, re
from pathlib import Path

# Load transcript
txt_content = Path(r"D:\zhihu\zhihu_url\runs\replay-20260518.combined-transcript.txt").read_text(encoding="utf-8")
txt_content = re.sub(r'^\[00:00:00 - 02:51:40\]\s*', '', txt_content)

# Load payload with events
with open(r"D:\zhihu\zhihu_url\runs\replay-20260518.payload.json", "r", encoding="utf-8") as f:
    payload = json.load(f)

events = payload.get("events", [])
total_duration = 10300.7  # seconds

# Split into sentences
sentences = re.split(r'(?<=[。！？；])', txt_content)
sentences = [s.strip() for s in sentences if s.strip()]
total_chars = sum(len(s) for s in sentences)
chars_per_second = total_chars / total_duration

def fmt_ts(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

# Build slide markers
slide_times = sorted([e["frame_idx"] for e in events if e.get("type") == "slide"])

# Walk through transcript and build sections
lines = []
lines.append("# 知乎直播回放 — 完整转写文档")
lines.append("")
lines.append("| 属性 | 值 |")
lines.append("|---|---|")
lines.append(f"| 日期 | 2026-05-18 |")
lines.append(f"| 时长 | {fmt_ts(int(total_duration))} |")
lines.append(f"| 总字符数 | {total_chars:,} |")
lines.append(f"| 句子数 | {len(sentences):,} |")
lines.append(f"| 幻灯片切换 | {len(slide_times)} 次 |")
lines.append(f"| 转写引擎 | SenseVoiceSmall (FunASR) + FSMN-VAD |")
lines.append(f"| 转写方式 | 回放视频离线转写 (完整文件) |")
lines.append(f"| 关键帧提取 | {payload.get('frames_count', 0)} 张 |")
lines.append("")
lines.append("---")
lines.append("")

# Process in sections defined by slide boundaries
slide_idx = 0
char_pos = 0
section_num = 1
current_slide_time = 0

# Add initial section
lines.append(f"## 第 {section_num} 部分 — {fmt_ts(0)}")
lines.append("")

section_sentences = []
for sent in sentences:
    approx_ts = char_pos / chars_per_second

    # Check if we crossed a slide boundary
    if slide_idx < len(slide_times) and approx_ts >= slide_times[slide_idx]:
        # Write current section
        for s in section_sentences:
            lines.append(s)
        section_sentences = []

        # Start new section
        section_num += 1
        slide_ts = slide_times[slide_idx]
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(f"## 第 {section_num} 部分 — {fmt_ts(slide_ts)}")
        lines.append("")
        slide_idx += 1

    # Add sentence with timestamp
    section_sentences.append(f"> [{fmt_ts(approx_ts)}] {sent}")
    char_pos += len(sent)

# Write remaining
for s in section_sentences:
    lines.append(s)

# Statistics
lines.append("")
lines.append("---")
lines.append("")
lines.append("## 转写统计信息")
lines.append("")
lines.append(f"| 指标 | 值 |")
lines.append(f"|---|---|")
lines.append(f"| 总字符数 | {total_chars:,} |")
lines.append(f"| 句子数 | {len(sentences):,} |")
lines.append(f"| 幻灯片切换 | {len(slide_times)} |")
lines.append(f"| 标注/画笔事件 | {sum(1 for e in events if e.get('type') == 'annotation')} |")
lines.append(f"| 关键帧提取 | {payload.get('frames_count', 0)} |")
lines.append(f"| 音频时长 | {fmt_ts(int(total_duration))} |")
lines.append(f"| 转写用时 | 614.6 秒 |")
lines.append(f"| 实时率 (RTF) | 0.053 |")
lines.append("")

out_path = Path(r"D:\zhihu\zhihu_url\runs\replay-20260518-final.md")
with open(out_path, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"Final markdown: {out_path}")
print(f"Lines: {len(lines)}")
print(f"Sections: {section_num}")
