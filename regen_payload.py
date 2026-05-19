"""Regenerate payload.json from existing transcript.json + re-extracted keyframes.

Run this instead of the full transcribe_replay.py when transcript.json already
exists and only the payload.json needs to be rebuilt (e.g. after a bug fix).

Keyframe extraction takes ~5-10 minutes on a 3-hour MP4; transcription is skipped.

Usage (Windows, from project root):
    python regen_payload.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, r"D:\zhihu\zhihu_url")

from zhihuTTS_video import extract_keyframes, build_gemini_payload

VIDEO_PATH      = Path(r"D:\zhihu\zhihu_url\Videos\replay-20260518.mp4")
TRANSCRIPT_JSON = Path(r"D:\zhihu\zhihu_url\runs\replay-20260518.transcript.json")
PAYLOAD_JSON    = Path(r"D:\zhihu\zhihu_url\runs\replay-20260518.payload.json")

if not VIDEO_PATH.exists():
    print(f"ERROR: video not found: {VIDEO_PATH}", file=sys.stderr)
    sys.exit(1)

if not TRANSCRIPT_JSON.exists():
    print(f"ERROR: transcript not found: {TRANSCRIPT_JSON}", file=sys.stderr)
    print("  Run transcribe_replay.py first.", file=sys.stderr)
    sys.exit(1)

print(f"Loading transcript: {TRANSCRIPT_JSON}")
with open(TRANSCRIPT_JSON, encoding="utf-8") as f:
    transcript = json.load(f)
print(f"  {len(transcript['segments'])} segments, total_s={transcript.get('total_s', '?')}")

print(f"\nExtracting keyframes from: {VIDEO_PATH.name}")
events, kept_frames = extract_keyframes(VIDEO_PATH)
print(f"  {len(kept_frames)} frames kept, {len(events)} events "
      f"(slide={sum(1 for e in events if e['type']=='slide')}, "
      f"annotation={sum(1 for e in events if e['type']=='annotation')})")

payload = build_gemini_payload(VIDEO_PATH.stem, transcript, events, kept_frames)

ser = {k: v for k, v in payload.items() if k != "frames"}
ser["frames_count"] = len(payload["frames"])
ser["frames"] = [
    {"path": f["path"], "timestamp_s": f["timestamp_s"], "marker": f["marker"]}
    for f in payload["frames"]
]

PAYLOAD_JSON.parent.mkdir(parents=True, exist_ok=True)
PAYLOAD_JSON.write_text(json.dumps(ser, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nDone: {PAYLOAD_JSON}")
print(f"  frames saved: {ser['frames_count']}")
print(f"\nNext step: set GEMINI_API_KEY and run:")
print(f"  python build_final_markdown.py")
