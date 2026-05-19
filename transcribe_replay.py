"""
Transcribe a replay MP4 by splitting audio into fixed-size chunks before ASR.

FunASR/SenseVoice 1.3.1 never returns sentence_info timestamps regardless of
merge_vad setting — it only returns ['key', 'text'].  The only way to get
accurate per-sentence timestamps is to split audio at the file level (fixed
60s slices), run SenseVoice on each slice, then add chunk_start_offset to each
resulting segment.  This mirrors what zhihuTTS_stream.py does for live slices.

Each chunk produces one coarse segment spanning [0, chunk_duration].  The
build_final_markdown.py step then distributes sub-sentence timestamps within
each segment's time window proportionally by character count.

Usage (Windows, from project root):
    python transcribe_replay.py

Optional env vars:
    REPLAY_CHUNK_S       Chunk size in seconds (default: 60)
    SENSEVOICE_DEVICE    cpu / cuda (default: cpu)
"""
import math
import os
import subprocess
import sys
import json
import tempfile
import time
from pathlib import Path

sys.path.insert(0, r"D:\zhihu\zhihu_url")
os.environ["TRANSCRIBE_BACKEND"] = "sensevoice"
os.environ.setdefault("SENSEVOICE_DEVICE", "cpu")

from zhihuTTS_video import (
    extract_keyframes,
    build_gemini_payload,
    transcript_to_text,
    _transcribe_sensevoice,  # type: ignore[attr-defined]
    _audio_duration_s,       # type: ignore[attr-defined]
    FFMPEG_TIMEOUT,
)

CHUNK_S = int(os.environ.get("REPLAY_CHUNK_S", "60"))

video_path = Path(r"D:\zhihu\zhihu_url\Videos\replay-20260518.mp4")
print(f"Processing : {video_path.name}")
print(f"Size       : {video_path.stat().st_size / 1024 / 1024:.0f} MB")
print(f"Chunk size : {CHUNK_S}s")

# Get total duration directly from the container (ffprobe supports MP4)
total_s = _audio_duration_s(video_path)
if total_s <= 0:
    print("ERROR: could not determine video duration", file=sys.stderr)
    sys.exit(1)

n_chunks = math.ceil(total_s / CHUNK_S)
print(f"Duration   : {total_s:.0f}s → {n_chunks} chunks\n")

# ── Chunked transcription ──────────────────────────────────────────────────
t0 = time.monotonic()
all_segments: list[dict] = []

for i in range(n_chunks):
    start_s    = i * CHUNK_S
    actual_dur = min(CHUNK_S, total_s - start_s)
    pct        = (i + 1) / n_chunks * 100
    print(f"[{i+1:3d}/{n_chunks}] {start_s:6.0f}s + {actual_dur:.0f}s  ({pct:.0f}%)", flush=True)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False, prefix="replay_chunk_") as fh:
        chunk_wav = Path(fh.name)

    try:
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-ss", str(start_s), "-t", str(actual_dur),
                "-i", str(video_path),
                "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                "-y", str(chunk_wav),
            ],
            check=True,
            capture_output=True,
            timeout=FFMPEG_TIMEOUT,
        )

        chunk_tr = _transcribe_sensevoice(chunk_wav)

        for seg in chunk_tr.get("segments", []):
            all_segments.append({
                "start": round(float(seg["start"]) + start_s, 3),
                "end":   round(float(seg["end"])   + start_s, 3),
                "text":  seg["text"],
                "words": seg.get("words", []),
            })
        n_segs = len(chunk_tr.get("segments", []))
        print(f"         → {n_segs} segment(s)", flush=True)

    except subprocess.CalledProcessError as e:
        print(f"  [warn] ffmpeg failed for chunk {i+1}: {e}", flush=True)
    finally:
        chunk_wav.unlink(missing_ok=True)

elapsed = time.monotonic() - t0
print(f"\nTranscription done: {elapsed:.0f}s elapsed, {len(all_segments)} segments total")

if not all_segments:
    print("ERROR: no segments transcribed — check audio content or SenseVoice setup", file=sys.stderr)
    sys.exit(1)

transcript = {
    "segments": all_segments,
    "backend_used": "sensevoice-chunked",
    "chunk_s": CHUNK_S,
    "total_s": round(total_s, 3),
    "n_chunks": n_chunks,
}

# ── Save outputs ───────────────────────────────────────────────────────────
out_dir = Path(r"D:\zhihu\zhihu_url\runs")
out_dir.mkdir(parents=True, exist_ok=True)
name = "replay-20260518"

json_path = out_dir / f"{name}.transcript.json"
with open(json_path, "w", encoding="utf-8") as f:
    json.dump(transcript, f, ensure_ascii=False, indent=2)
print(f"JSON  : {json_path}")

txt_path = out_dir / f"{name}.combined-transcript.txt"
txt = transcript_to_text(transcript)
with open(txt_path, "w", encoding="utf-8") as f:
    f.write(txt)
print(f"Text  : {txt_path}  ({len(txt)} chars, {len(all_segments)} segments)")

# ── Keyframe extraction (unchanged, on full video) ─────────────────────────
print("\nExtracting keyframes...")
try:
    events, kept_frames = extract_keyframes(video_path)
    payload = build_gemini_payload(video_path.stem, transcript, events, kept_frames)
    payload_path = out_dir / f"{name}.payload.json"
    with open(payload_path, "w", encoding="utf-8") as f:
        ser = {k: v for k, v in payload.items() if k != "frames"}
        ser["frames_count"] = len(payload["frames"])
        # Include frame paths so build_final_markdown.py can load images for Gemini
        ser["frames"] = [
            {"path": f["path"], "timestamp_s": f["timestamp_s"], "marker": f["marker"]}
            for f in payload["frames"]
        ]
        json.dump(ser, f, ensure_ascii=False, indent=2)
    print(f"Keyframes: {len(kept_frames)} kept, {len(events)} events")
except Exception as e:
    print(f"Keyframe extraction failed: {e}")

print("\nDone!")
