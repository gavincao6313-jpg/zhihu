from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from toutiao_common import REPO_ROOT, TOUTIAO_MANIFEST, TOUTIAO_PROBE_DIR, load_manifest, now_iso, slugify


DEFAULT_OUTPUT_DIR = REPO_ROOT / "Markdowns" / "source_cards" / "toutiao"


def latest_classification_report() -> Path:
    candidates = sorted(
        TOUTIAO_PROBE_DIR.glob("classify-*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(
            f"No classify-*.json found under {TOUTIAO_PROBE_DIR}. "
            "Run scripts/toutiao_classify_favorites.py first."
        )
    return candidates[0]


def load_classified_items(input_json: Path) -> list[dict]:
    data = json.loads(input_json.read_text(encoding="utf-8"))
    items = data.get("items") or []
    if not isinstance(items, list):
        raise ValueError(f"{input_json} does not contain a list at items[]")
    return [item for item in items if isinstance(item, dict)]


def load_manifest_records(manifest_path: Path) -> dict[str, dict]:
    manifest = load_manifest(manifest_path)
    return manifest.get("items") or {}


def format_card(item: dict, manifest_record: dict) -> str:
    item_id = item.get("item_id") or manifest_record.get("item_id") or "unknown"
    title = clean_text(item.get("title") or manifest_record.get("title") or item_id)
    content_type = item.get("content_type") or manifest_record.get("content_type") or "unknown"
    confidence = item.get("classification_confidence") or manifest_record.get(
        "classification_confidence", "unknown"
    )
    detail_url = item.get("detail_url") or manifest_record.get("detail_url") or ""
    abstract = clean_text(item.get("card_text") or manifest_record.get("card_text_excerpt") or "")
    raw_fields = item.get("raw_json_fields") or {}
    cover_url = first_image(item) or manifest_record.get("cover_url") or ""
    download_status = manifest_record.get("download_status", "pending")
    local_path = manifest_record.get("local_path", "")
    last_error = clean_text(manifest_record.get("last_error", ""))
    source_status = "metadata_only"
    if local_path and download_status == "done":
        source_status = "media_downloaded"
    elif download_status == "failed":
        source_status = "download_failed_metadata_only"

    lines = [
        f"# {title}",
        "",
        "> Toutiao source-card",
        f"> item_id: {item_id}",
        f"> source_type: {content_type}",
        f"> classification_confidence: {confidence}",
        f"> source_status: {source_status}",
        f"> captured_at: {now_iso()}",
        "",
        "## 1. Source",
        "",
        f"- URL: {detail_url or 'N/A'}",
        f"- Author/source: {clean_text(str(raw_fields.get('source') or manifest_record.get('author') or '')) or 'N/A'}",
        f"- Cover: {cover_url or 'N/A'}",
        f"- Local media: {local_path or 'N/A'}",
        f"- Download status: {download_status}",
    ]
    if last_error:
        lines.append(f"- Download error: {last_error}")

    lines.extend(
        [
            "",
            "## 2. Captured Metadata",
            "",
            f"- Chinese tag: {clean_text(str(raw_fields.get('chinese_tag') or '')) or 'N/A'}",
            f"- Article genre: {clean_text(str(raw_fields.get('article_genre') or '')) or 'N/A'}",
            f"- Duration: {clean_text(str(raw_fields.get('video_duration_str') or '')) or 'N/A'}",
            f"- Plays/details: {clean_text(str(raw_fields.get('go_detail_count') or raw_fields.get('detail_play_effective_count') or '')) or 'N/A'}",
            f"- Comments: {clean_text(str(raw_fields.get('comments_count') or '')) or 'N/A'}",
            f"- Repin time: {clean_text(str(raw_fields.get('repin_time') or '')) or 'N/A'}",
            "",
            "## 3. Abstract",
            "",
            abstract or "N/A",
            "",
            "## 4. Knowledge Ingest Strategy",
            "",
        ]
    )
    lines.extend(strategy_lines(content_type, source_status))
    lines.extend(
        [
            "",
            "## 5. Raw Classification Signals",
            "",
        ]
    )
    for signal in item.get("signals") or manifest_record.get("classification_signals") or []:
        lines.append(f"- {signal}")
    if not (item.get("signals") or manifest_record.get("classification_signals")):
        lines.append("- N/A")
    lines.append("")
    return "\n".join(lines)


def strategy_lines(content_type: str, source_status: str) -> list[str]:
    if content_type == "video":
        if source_status == "media_downloaded":
            return [
                "- Run short-video preprocess.",
                "- Then pack Qwen source-card synthesis with transcript and selected frames.",
            ]
        return [
            "- Keep as metadata-only source-card until the Ixigua/Toutiao media extraction path is fixed.",
            "- Do not mark as transcript-ready.",
            "- Prefer resolving playable media URL before ASR or multimodal synthesis.",
        ]
    if content_type == "article":
        return [
            "- Treat as text/article source.",
            "- Preserve captured abstract first.",
            "- Fetch full article body only if a real web URL is available; sslocal:// links are not downloadable web URLs.",
        ]
    if content_type == "image":
        return ["- Download original images, then OCR/VLM into a source-card appendix."]
    if content_type == "audio":
        return ["- Download audio stream, run ASR, then append full transcript."]
    return ["- Review manually before automated ingestion."]


def first_image(item: dict) -> str:
    for image in item.get("images") or []:
        src = image.get("src") or ""
        if src:
            return src
    return ""


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def write_cards(items: list[dict], manifest_records: dict[str, dict], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for item in items:
        item_id = item.get("item_id") or "unknown"
        title = item.get("title") or item_id
        filename = f"{item_id}-{slugify(title, default='toutiao')[:60]}.md"
        path = output_dir / filename
        record = manifest_records.get(item_id, {})
        path.write_text(format_card(item, record), encoding="utf-8")
        paths.append(path)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Build metadata source-cards from Toutiao classification reports")
    parser.add_argument("--input-json", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=TOUTIAO_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    input_json = args.input_json or latest_classification_report()
    items = load_classified_items(input_json)
    manifest_records = load_manifest_records(args.manifest)
    paths = write_cards(items, manifest_records, args.output_dir)
    print(f"Input report : {input_json}")
    print(f"Output dir   : {args.output_dir}")
    print(f"Cards written: {len(paths)}")
    for path in paths[:10]:
        print(f"  - {path}")
    if len(paths) > 10:
        print(f"  ... {len(paths) - 10} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
