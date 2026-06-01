"""
Process a replay MP4 video for QWEN sliding-window synthesis.

Two-stage pipeline:
  1. Full-video keyframe extraction (slide/annotation detection)
  2. Per-chunk SenseVoice transcription
  3. Distribute frames to chunks by timestamp → payload.json files
  4. Output format mirrors live pipeline so build_stream_markdown.py
     can consume it directly with --provider qwen.

Usage:
    python process_replay_qwen.py [video_path] [--base NAME]
"""
import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("TRANSCRIBE_BACKEND", "sensevoice")
os.environ.setdefault("SENSEVOICE_DEVICE", "cpu")
os.environ.setdefault("SENSEVOICE_MERGE_VAD", "true")

from zhihuTTS_video import (
    extract_keyframes,
    _transcribe_sensevoice,
    _audio_duration_s,
    FFMPEG_TIMEOUT,
)

CHUNK_S = 60


def fmt_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def distribute_frames_to_chunks(
    kept_frames: list[Path],
    events: list[dict],
    chunk_index: int,
    start_s: float,
    end_s: float,
    chunk_kf_dir: Path,
) -> tuple[list[dict], list[dict]]:
    """Copy frames belonging to [start_s, end_s) into chunk_kf_dir.

    Frame filenames from extract_keyframes are like frame_00042.jpg where
    the number is the frame index in the full extraction.  We need to
    approximate the timestamp from the frame index.

    Returns (chunk_frames, chunk_events).
    """
    chunk_frames: list[dict] = []
    chunk_events: list[dict] = []

    for frame_path in kept_frames:
        # frame_00123.jpg → frame index 122 (0-based)
        stem = frame_path.stem  # frame_00123
        try:
            frame_idx = int(stem.split("_")[1]) - 1
        except (IndexError, ValueError):
            continue

        # approx timestamp via frame index (extract_keyframes uses FRAME_FPS)
        # FRAME_FPS defaults to 1, so frame_idx ≈ seconds
        ts = float(frame_idx)

        if start_s <= ts < end_s:
            dest = chunk_kf_dir / frame_path.name
            if not dest.exists():
                shutil.copy2(str(frame_path), str(dest))
            chunk_frames.append({
                "path": str(dest.resolve()),
                "timestamp_s": round(ts, 3),
                "marker": f"Frame [{fmt_ts(ts)}] type=context diff=0",
            })

    # Also distribute events
    for evt in events:
        evt_frame_idx = evt.get("frame_idx", 0)
        evt_ts = float(evt_frame_idx)
        if start_s <= evt_ts < end_s:
            chunk_events.append(evt)

    return chunk_frames, chunk_events


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("video", nargs="?", default="Videos/replay-20260527-qwen-verify.mp4",
                    help="Path to replay MP4")
    ap.add_argument("--base", default="replay-20260527-qwen",
                    help="Base name for output files")
    ap.add_argument("--runs-dir", default="runs", help="Output directory")
    ap.add_argument("--keyframes-dir", default="Videos/keyframes",
                    help="Keyframes parent directory")
    ap.add_argument("--skip-keyframes", action="store_true",
                    help="Skip full-video keyframe extraction (use if already done)")
    args = ap.parse_args()

    video_path = Path(args.video)
    if not video_path.exists():
        print(f"ERROR: video not found: {video_path}", file=sys.stderr)
        sys.exit(1)

    runs_dir = Path(args.runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    kf_parent = Path(args.keyframes_dir)
    kf_parent.mkdir(parents=True, exist_ok=True)

    base = args.base
    run_ts = time.strftime("%Y%m%d-%H%M%S")

    print(f"Video     : {video_path}")
    print(f"Size      : {video_path.stat().st_size / 1024 / 1024:.0f} MB")
    print(f"Base name : {base}")
    print(f"Run TS    : {run_ts}")
    print(f"Chunk size: {CHUNK_S}s\n")

    # ── Step 1: Get duration ──────────────────────────────────────────────
    total_s = _audio_duration_s(video_path)
    if total_s <= 0:
        print("ERROR: could not determine video duration", file=sys.stderr)
        sys.exit(1)
    n_chunks = math.ceil(total_s / CHUNK_S)
    print(f"Duration  : {total_s:.0f}s → {n_chunks} chunks\n")

    # ── Step 2: Full-video keyframe extraction (once, high quality) ───────
    if not args.skip_keyframes:
        print("=" * 50)
        print("Extracting keyframes (full video, slide/annotation detection)...")
        print("=" * 50)
        t_kf = time.monotonic()
        try:
            events, kept_frames = extract_keyframes(video_path)
            kf_elapsed = time.monotonic() - t_kf
            print(f"Keyframes done: {len(kept_frames)} frames, {len(events)} events "
                  f"({kf_elapsed:.0f}s)\n")
        except Exception as e:
            print(f"Keyframe extraction failed: {e}", file=sys.stderr)
            print("Continuing without keyframes — synthesis will lack visual evidence.\n")
            events, kept_frames = [], []
    else:
        events, kept_frames = [], []
        print("Skipping keyframe extraction (--skip-keyframes)\n")

    # ── Step 3: Per-chunk transcription ───────────────────────────────────
    print("=" * 50)
    print("Transcribing audio chunks with SenseVoice...")
    print("=" * 50)
    t0 = time.monotonic()
    all_segments: list[dict] = []
    chunk_files: list[Path] = []

    for i in range(n_chunks):
        start_s = i * CHUNK_S
        actual_dur = min(CHUNK_S, total_s - start_s)
        chunk_label = f"chunk{i+1:03d}_{start_s}s"
        pct = (i + 1) / n_chunks * 100
        print(f"[{i+1:3d}/{n_chunks}] {start_s:6.0f}s + {actual_dur:.0f}s  ({pct:.0f}%)",
              flush=True)

        # Chunk keyframes directory
        chunk_kf_dir = kf_parent / f"{base}_{chunk_label}"
        chunk_kf_dir.mkdir(parents=True, exist_ok=True)

        # Distribute global frames to this chunk
        chunk_frames, chunk_events = distribute_frames_to_chunks(
            kept_frames, events, i + 1, start_s, start_s + actual_dur, chunk_kf_dir,
        )

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False,
                                         prefix="replay_chunk_") as fh:
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
                check=True, capture_output=True, timeout=FFMPEG_TIMEOUT,
            )

            chunk_tr = _transcribe_sensevoice(chunk_wav)
            segments = chunk_tr.get("segments", [])

            transcript_lines = []
            for seg in segments:
                seg_start = round(float(seg["start"]) + start_s, 3)
                seg_end = round(float(seg["end"]) + start_s, 3)
                all_segments.append({
                    "start": seg_start, "end": seg_end,
                    "text": seg["text"], "words": seg.get("words", []),
                })
                transcript_lines.append(
                    f"[{fmt_ts(seg_start)} - {fmt_ts(seg_end)}] {seg['text']}"
                )

            full_transcript = "\n".join(transcript_lines) if transcript_lines else ""

            # ── Save chunk outputs ──
            chunk_ts_file = runs_dir / (
                f"stream-{base}_{chunk_label}-{run_ts}.global-transcript.txt"
            )
            chunk_ts_file.write_text(full_transcript, encoding="utf-8")

            chunk_transcript_text = " ".join(seg["text"] for seg in segments)
            payload = {
                "video_name": f"{base}_{chunk_label}",
                "full_text": chunk_transcript_text,
                "frames": chunk_frames,
                "events": chunk_events,
                "stats": {
                    "slide_changes": sum(1 for e in chunk_events
                                         if e.get("type") == "slide"),
                    "annotations": sum(1 for e in chunk_events
                                       if e.get("type") == "annotation"),
                    "frames_total": len(chunk_frames),
                    "text_chars": len(chunk_transcript_text),
                },
            }
            chunk_payload_file = runs_dir / (
                f"stream-{base}_{chunk_label}-{run_ts}.payload.json"
            )
            chunk_payload_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
            )

            chunk_files.append(chunk_ts_file)
            print(f"         → {len(segments)} segments, {len(chunk_frames)} frames",
                  flush=True)

        except subprocess.CalledProcessError as e:
            print(f"  [warn] ffmpeg failed: {e}", flush=True)
        finally:
            chunk_wav.unlink(missing_ok=True)

    elapsed = time.monotonic() - t0
    print(f"\nTranscription done: {elapsed:.0f}s, {len(all_segments)} segments total\n")

    if not all_segments:
        print("ERROR: no segments transcribed", file=sys.stderr)
        sys.exit(1)

    # ── Step 4: Save combined transcript ──────────────────────────────────
    full_txt_lines = [
        f"[{fmt_ts(seg['start'])} - {fmt_ts(seg['end'])}] {seg['text']}"
        for seg in all_segments
    ]
    combined_txt = "\n".join(full_txt_lines)
    txt_path = runs_dir / f"stream-{base}-{run_ts}.combined-transcript.txt"
    txt_path.write_text(combined_txt, encoding="utf-8")
    print(f"Combined transcript: {txt_path} ({len(combined_txt):,} chars)")

    # ── Step 5: Manifest ──────────────────────────────────────────────────
    manifest = {
        "base": base, "run_ts": run_ts,
        "video": str(video_path.resolve()),
        "total_s": round(total_s, 3), "n_chunks": n_chunks, "chunk_s": CHUNK_S,
        "total_segments": len(all_segments), "total_chars": len(combined_txt),
        "total_frames": len(kept_frames), "total_events": len(events),
        "elapsed_s": round(elapsed, 1),
        "chunk_files": [str(cf) for cf in chunk_files],
    }
    manifest_path = runs_dir / f"stream-{base}-{run_ts}.manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(f"Manifest: {manifest_path}")

    # ── Step 6: Instructions ──────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("Ready for QWEN sliding-window synthesis!")
    print(f"{'='*60}")
    print(f"  python scripts/build_stream_markdown.py --base {base}")
    print(f"    --provider qwen --runs-dir {runs_dir}")
    print(f"    --synthesis-pass sliding-window")
    print(f"\nMake sure DASHSCOPE_API_KEY is set.")
    print(f"Total frames available: {len(kept_frames)}")


if __name__ == "__main__":
    main()
