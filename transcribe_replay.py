import sys, json, time, os
from pathlib import Path

sys.path.insert(0, r"D:\zhihu\zhihu_url")
os.environ["TRANSCRIBE_BACKEND"] = "sensevoice"
os.environ["SENSEVOICE_DEVICE"] = "cpu"

from zhihuTTS_video import transcribe_audio, extract_keyframes, build_gemini_payload, transcript_to_text

video_path = Path(r"D:\zhihu\zhihu_url\Videos\replay-20260518.mp4")
print(f"Processing: {video_path.name}")
print(f"Size: {video_path.stat().st_size / 1024 / 1024:.0f} MB")

# Transcribe
t0 = time.monotonic()
transcript = transcribe_audio(video_path)
elapsed = time.monotonic() - t0
print(f"Transcription completed in {elapsed:.0f}s")

# Save output
out_dir = Path(r"D:\zhihu\zhihu_url\runs")
out_dir.mkdir(parents=True, exist_ok=True)
name = "replay-20260518"

# Save JSON
json_path = out_dir / f"{name}.transcript.json"
with open(json_path, "w", encoding="utf-8") as f:
    json.dump(transcript, f, ensure_ascii=False, indent=2)
print(f"JSON saved: {json_path}")

# Save formatted text
txt_path = out_dir / f"{name}.combined-transcript.txt"
txt = transcript_to_text(transcript)
with open(txt_path, "w", encoding="utf-8") as f:
    f.write(txt)
print(f"Text saved: {txt_path} ({len(txt)} chars, {len(transcript['segments'])} segments)")

# Keyframe extraction
print("\nExtracting keyframes...")
try:
    events, kept_frames = extract_keyframes(video_path)
    payload = build_gemini_payload(video_path.stem, transcript, events, kept_frames)
    payload_path = out_dir / f"{name}.payload.json"
    with open(payload_path, "w", encoding="utf-8") as f:
        ser = {k: v for k, v in payload.items() if k != "frames"}
        ser["frames_count"] = len(payload["frames"])
        json.dump(ser, f, ensure_ascii=False, indent=2)
    print(f"Keyframes: {len(kept_frames)} kept, {len(events)} events")
except Exception as e:
    print(f"Keyframe extraction failed: {e}")

print("\nDone!")
