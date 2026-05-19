"""Debug: probe SenseVoice raw output structure with merge_vad=False."""
import sys, json, os, subprocess
from pathlib import Path

sys.path.insert(0, r"D:\zhihu\zhihu_url")
os.environ["TRANSCRIBE_BACKEND"] = "sensevoice"
os.environ["SENSEVOICE_DEVICE"] = "cpu"

# Extract first 5 minutes of audio for quick debug
video_path = Path(r"D:\zhihu\zhihu_url\Videos\replay-20260518.mp4")
wav_path = Path(r"D:\zhihu\zhihu_url\Videos\.tmp\debug_first5min.wav")
wav_path.parent.mkdir(parents=True, exist_ok=True)

print("Extracting first 5 minutes of audio...")
subprocess.run([
    "ffmpeg", "-i", str(video_path),
    "-vn", "-acodec", "pcm_s16le",
    "-ar", "16000", "-ac", "1",
    "-t", "300",
    "-y", str(wav_path),
], capture_output=True, check=True, timeout=300)

from funasr import AutoModel

print("Loading model...")
model = AutoModel(
    model="iic/SenseVoiceSmall",
    vad_model="fsmn-vad",
    device="cpu",
    disable_update=True,
)

print("Running generate with merge_vad=False...")
result = model.generate(
    input=str(wav_path),
    cache={},
    language="zh",
    use_itn=True,
    batch_size_s=60,
    merge_vad=False,
)

print(f"\nResult list length: {len(result)}")
for i, item in enumerate(result):
    print(f"\n--- Result[{i}] ---")
    print(f"  type: {type(item).__name__}")
    if isinstance(item, dict):
        print(f"  keys: {list(item.keys())}")
        for k, v in item.items():
            if isinstance(v, list):
                print(f"  {k}: list[{len(v)}]")
                for j, elem in enumerate(v[:5]):
                    if isinstance(elem, dict):
                        print(f"    [{j}] keys={list(elem.keys())}: {json.dumps(elem, ensure_ascii=False)[:300]}")
                    else:
                        print(f"    [{j}] {str(elem)[:200]}")
            elif isinstance(v, str):
                print(f"  {k}: str[{len(v)}] = {v[:200]}")
            else:
                print(f"  {k}: {v}")
    else:
        print(f"  value: {str(item)[:300]}")

# Now test with merge_vad=True for comparison
print("\n\n=== Now testing with merge_vad=True ===")
result2 = model.generate(
    input=str(wav_path),
    cache={},
    language="zh",
    use_itn=True,
    batch_size_s=60,
    merge_vad=True,
    merge_length_s=15,
)

print(f"\nResult list length: {len(result2)}")
for i, item in enumerate(result2):
    print(f"\n--- Result[{i}] ---")
    if isinstance(item, dict):
        print(f"  keys: {list(item.keys())}")
        for k, v in item.items():
            if isinstance(v, list):
                print(f"  {k}: list[{len(v)}]")
                for j, elem in enumerate(v[:5]):
                    if isinstance(elem, dict):
                        print(f"    [{j}] keys={list(elem.keys())}: {json.dumps(elem, ensure_ascii=False)[:300]}")
            elif isinstance(v, str):
                print(f"  {k}: str[{len(v)}] = {v[:200]}")

wav_path.unlink(missing_ok=True)
