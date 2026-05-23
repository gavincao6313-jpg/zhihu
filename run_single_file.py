"""Run zhihuTTS file pipeline on a single video for A/B testing."""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.chdir(str(Path(__file__).parent))

from zhihuTTS import process_video, tprint, MARKDOWNS_DIR
from google import genai
from google.genai import types
from datetime import date

video_path = Path(sys.argv[1])
api_key = os.environ["OPENCLAW_GOOGLE_API_KEY"]

base_url = os.environ.get("GEMINI_BASE_URL", "")
http_opts = types.HttpOptions(
    timeout=3600000,
    base_url=base_url or None,
    api_version=os.environ.get("GEMINI_API_VERSION", "v1beta") if base_url else None,
)
client = genai.Client(api_key=api_key, http_options=http_opts)

date_prefix = date.today().strftime("%m%d")
output_path = MARKDOWNS_DIR / f"TTS_{date_prefix}_{video_path.stem}.md"
MARKDOWNS_DIR.mkdir(exist_ok=True)

result = process_video(client, video_path, output_path, f"AB-file {video_path.stem[:40]}")
print(f"\nResult: {result}")

try:
    from extract_slides import extract_slides

    extract_slides(video_path)
except Exception as exc:
    print(f"[warn] 幻灯片提取失败，不影响 Markdown 主产物: {exc}")
