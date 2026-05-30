"""Convert single payload.json to per-chunk stream format for build_stream_markdown.py.

Usage:
    python scripts/convert_payload_to_chunks.py <payload.json> <base_name> [runs_dir]

Example:
    python scripts/convert_payload_to_chunks.py cache/payload/video.payload.json replay-20260530

Output (in runs/):
    stream-{base}_chunk001_1s.global-transcript.txt   full transcript (chunk001 only)
    stream-{base}_chunk001_1s.payload.json             frames for this 60s window
    stream-{base}_chunk002_61s.global-transcript.txt  empty  (fallback to full transcript)
    stream-{base}_chunk002_61s.payload.json
    ...
    stream-{base}.combined-transcript.txt
    stream-base-{base}.txt

Timeline: last chunk start ≈ max_ts → load_chunk_segments() produces correct timeline_end_s.
Transcript: build_combined_transcript() reads chunk001 only → full text without duplication.
Windows: _transcript_for_window() returns "" for non-chunk001 windows → falls back to full.
"""
import json, sys, math
from pathlib import Path


def _fmt_ts(s: int) -> str:
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _enrich_frame_markers(frames: list, events: list) -> list:
    """Ensure frame markers carry correct type=slide/annotation from events.

    Idempotent: skips frames already correctly typed. Fixes frames whose
    marker is missing or carries type=context despite a matching event.
    Needed when payload was generated without marker field, or when
    frame_marker() event-matching failed at extraction time.
    """
    if not events:
        return frames
    by_idx = {e["frame_idx"]: e for e in events}
    for f in frames:
        current = f.get("marker", "")
        if "type=slide" in current or "type=annotation" in current:
            continue  # already correctly typed — skip
        ts = f.get("timestamp_s", 0)
        # Try 1-based filename → 0-based event index (ts-1), then ts as fallback
        ev = by_idx.get(ts - 1) or by_idx.get(ts)
        etype = ev.get("type") if ev else None
        if etype in ("slide", "annotation"):
            diff = ev.get("diff", 0)
            f["marker"] = f"Frame [{_fmt_ts(ts)}] type={etype} diff={diff}"
        elif not current:
            f["marker"] = f"Frame [{_fmt_ts(ts)}] type=context diff=0"
    return frames

if len(sys.argv) < 3:
    print("Usage: convert_payload_to_chunks.py <payload.json> <base_name> [runs_dir]")
    sys.exit(1)

payload_path = Path(sys.argv[1])
base_name    = sys.argv[2]
runs_dir     = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("runs")

payload    = json.loads(payload_path.read_text(encoding="utf-8"))
full_text  = payload["full_text"]
frames     = payload["frames"]
video_name = payload["video_name"]
stats      = payload.get("stats", {})
events     = payload.get("events", [])

# Fix markers that are missing or all-context despite events existing in payload
frames = _enrich_frame_markers(frames, events)

max_ts        = max(f["timestamp_s"] for f in frames) if frames else 0
chunk_dur     = 60
total_chunks  = max(1, math.ceil(max_ts / chunk_dur))

runs_dir.mkdir(parents=True, exist_ok=True)

print(f"Video   : {video_name}")
print(f"Duration: {max_ts:.0f}s  Chunks: {total_chunks}  Frames: {len(frames)}  Text: {len(full_text)} chars")

for i in range(total_chunks):
    chunk_start = max(1, i * chunk_dur)   # 1-based first chunk matches live stream convention
    chunk_end   = chunk_start + chunk_dur
    chunk_id    = f"{i + 1:03d}"
    stem        = f"stream-{base_name}_chunk{chunk_id}_{chunk_start}s"

    # Distribute frames: those whose timestamp falls in [chunk_start-1, chunk_end)
    chunk_frames = [f for f in frames
                    if chunk_start - 1 <= f["timestamp_s"] < chunk_end]

    # Transcript: full text in chunk001 only; empty elsewhere.
    # build_combined_transcript concatenates all; non-empty only once avoids duplication.
    # _transcript_for_window falls back to full transcript when segment text is empty.
    chunk_text = full_text if i == 0 else ""

    # global-transcript.txt
    gt_path = runs_dir / f"{stem}.global-transcript.txt"
    gt_path.write_text(chunk_text, encoding="utf-8")

    # transcript.txt
    tr_path = runs_dir / f"{stem}.transcript.txt"
    tr_path.write_text(chunk_text, encoding="utf-8")

    # payload.json
    chunk_payload = {
        "video_name":  video_name,
        "chunk_index": i,
        "start_s":     chunk_start,
        "end_s":       chunk_end,
        "frames":      chunk_frames,
        "stats": {
            "slide_changes": stats.get("slide_changes", 0),
            "annotations":   stats.get("annotations",   0),
            "frames_total":  len(chunk_frames),
        },
    }
    pl_path = runs_dir / f"{stem}.payload.json"
    pl_path.write_text(json.dumps(chunk_payload, ensure_ascii=False, indent=2), encoding="utf-8")

# Combined transcript
combined_path = runs_dir / f"stream-{base_name}.combined-transcript.txt"
combined_path.write_text(full_text, encoding="utf-8")

# Base marker
marker_path = runs_dir / f"stream-base-{base_name}.txt"
marker_path.write_text(base_name, encoding="utf-8")

print(f"\nDone. {total_chunks} chunks → {runs_dir}/stream-{base_name}_*")
print(f"\nRun Qwen synthesis:")
print(f"  set DASHSCOPE_API_KEY=your_key")
print(f"  set QWEN_MODEL=qwen3.6-plus")
print(f"  python scripts\\build_stream_markdown.py --base {base_name} --provider qwen --qwen-max-frames 128")
