"""
A/B Test — URL Branch: download from CDN URL + chunked transcription (60s slices).

Usage:
    cd D:\zhihu\zhihu_url
    set TRANSCRIBE_BACKEND=sensevoice
    set SENSEVOICE_DEVICE=cpu
    python run_ab_url.py
"""
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("TRANSCRIBE_BACKEND", "sensevoice")
os.environ.setdefault("SENSEVOICE_DEVICE", "cpu")
os.environ["SENSEVOICE_MERGE_VAD"] = "false"  # precise VAD boundaries

sys.path.insert(0, str(Path(__file__).parent))

from zhihuTTS_video import (
    extract_keyframes,
    build_gemini_payload,
    transcript_to_text,
    _transcribe_sensevoice,
    _audio_duration_s,
    FFMPEG_TIMEOUT,
)

CDN_URL = (
    "https://vdn6.vzuu.com/FHD/db7b37de-5397-11f1-9ab9-9e69130559ce-v8_f2_t1_FH0av9Me.mp4"
    "?pkey=AAX30P1x_wIpRTQjuoa-YJHsEB87Bs3fIafAA-I6eiShhdF_4tPLrWwBlwBxn-"
    "vi0tDLHyn3Z_R_AU9aifK45VQK&bu=178e6938&c=avc.8.0&expiration=1779267733"
    "&f=mp4&pu=178e6938&v=ks6"
)
NAME = "ab-url-english-practice"
VIDEOS_DIR = Path(r"D:\zhihu\zhihu_url\Videos")
RUNS_DIR = Path(r"D:\zhihu\zhihu_url\runs")
MARKDOWNS_DIR = Path(r"D:\zhihu\zhihu_url\Markdowns")
VIDEO_PATH = VIDEOS_DIR / f"{NAME}.mp4"
CHUNK_S = 60

VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
RUNS_DIR.mkdir(parents=True, exist_ok=True)
MARKDOWNS_DIR.mkdir(parents=True, exist_ok=True)

print("=" * 60)
print(f"A/B Test — URL Branch (chunked 60s)")
print(f"URL : {CDN_URL[:80]}...")
print("=" * 60)

t0 = time.monotonic()

# ── Step 1: Download video from CDN URL ──
print("\n[1/4] Downloading video from CDN URL...")
t1 = time.monotonic()
if VIDEO_PATH.exists():
    print(f"  Already exists: {VIDEO_PATH} ({VIDEO_PATH.stat().st_size / 1024 / 1024:.0f} MB)")
else:
    subprocess.run(
        ["curl", "-L", "-o", str(VIDEO_PATH), CDN_URL],
        check=True,
        timeout=7200,
    )
    dl_size = VIDEO_PATH.stat().st_size / 1024 / 1024
    print(f"  Downloaded: {dl_size:.0f} MB")
dl_elapsed = time.monotonic() - t1
print(f"  Download done ({dl_elapsed:.0f}s)")

# ── Step 2: Keyframe extraction ──
print("\n[2/4] Extracting keyframes...")
t2 = time.monotonic()
events, kept_frames = extract_keyframes(VIDEO_PATH)
kf_elapsed = time.monotonic() - t2
print(f"  Done: {len(events)} events, {len(kept_frames)} frames kept ({kf_elapsed:.0f}s)")

# ── Step 3: Chunked transcription (60s slices) ──
print("\n[3/4] Transcribing (chunked 60s SenseVoice)...")
t3 = time.monotonic()

total_s = _audio_duration_s(VIDEO_PATH)
if total_s <= 0:
    print("ERROR: could not determine video duration", file=sys.stderr)
    sys.exit(1)

n_chunks = math.ceil(total_s / CHUNK_S)
print(f"  Duration: {total_s:.0f}s → {n_chunks} chunks")

all_segments: list[dict] = []
for i in range(n_chunks):
    start_s = i * CHUNK_S
    actual_dur = min(CHUNK_S, total_s - start_s)
    pct = (i + 1) / n_chunks * 100
    print(f"  [{i+1:3d}/{n_chunks}] {start_s:6.0f}s + {actual_dur:.0f}s  ({pct:.0f}%)", flush=True)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False, prefix="ab_url_chunk_") as fh:
        chunk_wav = Path(fh.name)

    try:
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-ss", str(start_s), "-t", str(actual_dur),
                "-i", str(VIDEO_PATH),
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

tr_elapsed = time.monotonic() - t3
print(f"  Done: {len(all_segments)} total segments ({tr_elapsed:.0f}s)")

transcript = {
    "segments": all_segments,
    "backend_used": "sensevoice-chunked",
    "chunk_s": CHUNK_S,
    "total_s": round(total_s, 3),
    "n_chunks": n_chunks,
}

# ── Step 4: Save outputs ──
print("\n[4/4] Saving outputs...")

transcript_json = RUNS_DIR / f"{NAME}.transcript.json"
with open(transcript_json, "w", encoding="utf-8") as f:
    json.dump(transcript, f, ensure_ascii=False, indent=2)
print(f"  Transcript JSON: {transcript_json}")

txt = transcript_to_text(transcript)
txt_path = RUNS_DIR / f"{NAME}.combined-transcript.txt"
txt_path.write_text(txt, encoding="utf-8")
print(f"  Combined text : {txt_path} ({len(txt):,} chars)")

payload = build_gemini_payload(VIDEO_PATH.stem, transcript, events, kept_frames)
payload_json = RUNS_DIR / f"{NAME}.payload.json"
ser = {
    "video_name": payload["video_name"],
    "full_text": payload["full_text"],
    "frames": [{"path": f["path"], "timestamp_s": f["timestamp_s"], "marker": f["marker"]}
               for f in payload["frames"]],
    "events": payload["events"],
    "stats": payload["stats"],
    "frames_count": len(payload["frames"]),
}
with open(payload_json, "w", encoding="utf-8") as f:
    json.dump(ser, f, ensure_ascii=False, indent=2)
print(f"  Payload JSON  : {payload_json}")

total_elapsed = time.monotonic() - t0
print(f"\n{'=' * 60}")
print(f"URL branch complete! ({total_elapsed:.0f}s total)")
print(f"  Download   : {dl_elapsed:.0f}s")
print(f"  Keyframes  : {kf_elapsed:.0f}s")
print(f"  Transcrip  : {tr_elapsed:.0f}s")
print(f"  Segments   : {len(all_segments)}")
print(f"  Text chars : {len(txt):,}")
print(f"  Events     : {len(events)}")
print(f"Outputs in: {RUNS_DIR}")
print(f"{'=' * 60}")
