"""Probe the raw SenseVoice result structure."""
import sys, json
from pathlib import Path

sys.path.insert(0, r"D:\zhihu\zhihu_url")

# Load the saved raw transcript JSON
json_path = Path(r"D:\zhihu\zhihu_url\runs\replay-20260518.transcript.json")
with open(json_path, "r", encoding="utf-8") as f:
    data = json.load(f)

print("Top-level keys:", list(data.keys()))
print(f"Segments: {len(data['segments'])}")
if data["segments"]:
    seg = data["segments"][0]
    print(f"Segment 0 keys: {list(seg.keys())}")
    print(f"  start: {seg['start']}, end: {seg['end']}")
    print(f"  text length: {len(seg['text'])}")

# Check if there's a raw_result key
if "raw_result" in data:
    print("\nraw_result present")
    raw = data["raw_result"]
    print(f"  type: {type(raw)}")
    if isinstance(raw, list):
        print(f"  len: {len(raw)}")
        for i, item in enumerate(raw[:3]):
            if isinstance(item, dict):
                print(f"  item[{i}] keys: {list(item.keys())}")
                for k, v in item.items():
                    if isinstance(v, list):
                        print(f"    {k}: list of {len(v)}")
                        if v:
                            print(f"      first element type: {type(v[0])}")
                            if isinstance(v[0], dict):
                                print(f"      first keys: {list(v[0].keys())}")
                    elif isinstance(v, str):
                        print(f"    {k}: str({len(v)})")
                    else:
                        print(f"    {k}: {v}")
else:
    print("\nNo raw_result key - the transcript was processed before saving")
    print("The script only saved the processed segments, not raw SenseVoice output")

# Let's re-run with raw output capture
print("\n" + "=" * 60)
print("Re-running with raw output capture...")

import os
os.environ["TRANSCRIBE_BACKEND"] = "sensevoice"
os.environ["SENSEVOICE_DEVICE"] = "cpu"

from funasr import AutoModel
from funasr.utils.postprocess_utils import rich_transcription_postprocess

wav_path = Path(r"D:\zhihu\zhihu_url\Videos\.tmp\zhihu_replay_audio.wav")

# First, extract audio if not already done
import subprocess
print("Extracting audio...")
subprocess.run([
    "ffmpeg", "-i", str(Path(r"D:\zhihu\zhihu_url\Videos\replay-20260518.mp4")),
    "-vn", "-acodec", "pcm_s16le",
    "-ar", "16000", "-ac", "1",
    "-y", str(wav_path),
], capture_output=True, check=True, timeout=7200)

print("Loading model...")
model = AutoModel(
    model="iic/SenseVoiceSmall",
    vad_model="fsmn-vad",
    device="cpu",
    disable_update=True,
)

print("Running generate...")
result = model.generate(
    input=str(wav_path),
    cache={},
    language="zh",
    use_itn=True,
    batch_size_s=60,
    merge_vad=True,
    merge_length_s=15,
)

print(f"\nResult type: {type(result)}")
print(f"Result len: {len(result)}")

for i, item in enumerate(result):
    print(f"\n--- Item {i} ---")
    print(f"  type: {type(item)}")
    if isinstance(item, dict):
        print(f"  keys: {list(item.keys())}")
        for k, v in item.items():
            if isinstance(v, list):
                print(f"  {k}: list of {len(v)}")
                if v and len(v) > 0:
                    elem = v[0]
                    print(f"    first element type: {type(elem)}")
                    if isinstance(elem, dict):
                        print(f"    first keys: {list(elem.keys())}")
                        # Show first 2 sentence_info if exists
                        if k == "sentence_info":
                            for si, sent in enumerate(v[:3]):
                                print(f"    sentence[{si}]: {json.dumps(sent, ensure_ascii=False)[:300]}")
            elif isinstance(v, str):
                print(f"  {k}: str({len(v)}) = {v[:200]}")
            else:
                print(f"  {k}: {v}")
    else:
        print(f"  value: {str(item)[:200]}")

# Cleanup
wav_path.unlink(missing_ok=True)
