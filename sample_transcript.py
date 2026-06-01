import re
from pathlib import Path

txt = Path(r"D:\zhihu\zhihu_url\runs\replay-20260518.combined-transcript.txt").read_text(encoding="utf-8")
txt = re.sub(r'^\[00:00:00 - 02:51:40\]\s*', '', txt)

sentences = re.split(r'(?<=[。！？；])', txt)
sentences = [s.strip() for s in sentences if s.strip()]
total = len(sentences)

for pct, label in [(0.05, "5%"), (0.10, "10%"), (0.20, "20%"), (0.30, "30%"), (0.40, "40%"), (0.50, "50%"), (0.60, "60%"), (0.70, "70%"), (0.80, "80%"), (0.90, "90%"), (0.95, "95%")]:
    idx = int(total * pct)
    chunk = sentences[idx:idx+5]
    print(f"\n=== {label} (sentence {idx}/{total}) ===")
    for s in chunk:
        print(s[:200])
