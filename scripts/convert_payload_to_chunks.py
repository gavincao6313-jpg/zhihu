"""Convert single payload.json to per-chunk stream format for build_stream_markdown.py."""
import json, sys, os
from pathlib import Path

payload_path = Path(sys.argv[1])
base_name = sys.argv[2]  # e.g. "replay-verify-20260530"
runs_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("runs")

payload = json.loads(payload_path.read_text(encoding="utf-8"))
full_text = payload["full_text"]
frames = payload["frames"]
video_name = payload["video_name"]

# Split into 60s chunks based on frame timestamps
chunk_duration = 60
max_ts = max(f["timestamp_s"] for f in frames) if frames else 0
total_chunks = int(max_ts / chunk_duration) + 1

print(f"Video: {video_name}")
print(f"Duration: {max_ts:.0f}s, Chunks: {total_chunks}, Frames: {len(frames)}, Text: {len(full_text)} chars")

# Create ONE mega-chunk covering full duration so _transcript_for_window matches all windows.
# Start at 1s (not 0s) to match live stream chunk naming convention.
chunk_id = "001"
chunk_start = 1
chunk_end = max(1, int(max_ts) + 60)

# Transcript chunk
transcript_path = runs_dir / f"stream-{base_name}_chunk{chunk_id}_{chunk_start}s.transcript.txt"
transcript_path.parent.mkdir(parents=True, exist_ok=True)
transcript_path.write_text(full_text, encoding="utf-8")

# Global transcript — full text, full duration
global_path = runs_dir / f"stream-{base_name}_chunk{chunk_id}_{chunk_start}s.global-transcript.txt"
global_path.write_text(full_text, encoding="utf-8")

# Payload — all frames
payload_chunk = {
    "video_name": video_name,
    "chunk_index": 0,
    "start_s": chunk_start,
    "end_s": chunk_end,
    "frames": frames,
    "stats": {
        "slide_changes": payload["stats"]["slide_changes"],
        "annotations": payload["stats"]["annotations"],
        "frames_total": len(frames),
    }
}
payload_chunk_path = runs_dir / f"stream-{base_name}_chunk{chunk_id}_{chunk_start}s.payload.json"
payload_chunk_path.write_text(json.dumps(payload_chunk, ensure_ascii=False, indent=2), encoding="utf-8")

# Write combined transcript
combined_path = runs_dir / f"stream-{base_name}.combined-transcript.txt"
combined_path.write_text(full_text, encoding="utf-8")

# Write base marker
marker_path = runs_dir / f"stream-base-{base_name}.txt"
marker_path.write_text(base_name, encoding="utf-8")

print(f"Done. Chunks written to {runs_dir}/stream-{base_name}_*")
print(f"Run: build_stream_markdown.py --base {base_name} --provider qwen --synthesis-pass one-shot --qwen-max-frames 128")
