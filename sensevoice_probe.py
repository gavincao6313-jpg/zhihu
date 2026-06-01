from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from funasr import AutoModel
from funasr.utils.postprocess_utils import rich_transcription_postprocess


ROOT = Path(__file__).parent
RUNS = ROOT / "runs"


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe SenseVoice transcription on one media file.")
    parser.add_argument("input", help="Audio or video path accepted by FunASR.")
    parser.add_argument("--model", default="iic/SenseVoiceSmall")
    parser.add_argument("--vad-model", default="fsmn-vad")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--language", default="zh", help="Use zh to prefer Chinese output.")
    parser.add_argument("--name", default="sensevoice-probe")
    args = parser.parse_args()

    input_path = Path(args.input)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_stem = f"{args.name}-{input_path.stem}-{timestamp}"
    json_path = RUNS / f"{out_stem}.json"
    txt_path = RUNS / f"{out_stem}.txt"
    RUNS.mkdir(exist_ok=True)

    model = AutoModel(
        model=args.model,
        vad_model=args.vad_model,
        device=args.device,
        disable_update=True,
    )
    result = model.generate(
        input=str(input_path),
        cache={},
        language=args.language,
        use_itn=True,
        batch_size_s=60,
        merge_vad=True,
        merge_length_s=15,
    )
    text_parts = []
    for item in result:
        raw_text = str(item.get("text", ""))
        text_parts.append(rich_transcription_postprocess(raw_text))
    text = "\n".join(part for part in text_parts if part)

    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    txt_path.write_text(text, encoding="utf-8")
    print(f"JSON: {json_path}")
    print(f"Text: {txt_path}")
    print(text[:2000])


if __name__ == "__main__":
    main()
