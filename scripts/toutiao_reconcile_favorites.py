from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from toutiao_common import REPO_ROOT, TOUTIAO_MANIFEST, TOUTIAO_PROBE_DIR, load_manifest, write_json


DEFAULT_PAYLOAD_DIR = REPO_ROOT / "runs" / "short-video" / "preprocess"
DEFAULT_MARKDOWN_DIR = REPO_ROOT / "Markdowns"
DEFAULT_SOURCE_CARD_DIR = REPO_ROOT / "Markdowns" / "source_cards" / "toutiao"
DEFAULT_OUTPUT_DIR = TOUTIAO_PROBE_DIR


def short_id(video_id: str) -> str:
    parts = (video_id or "").split("-")
    if len(parts) >= 2 and parts[0] == "toutiao":
        return "-".join(parts[:2])
    return video_id


def build_payload_index(payload_dir: Path) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for path in sorted(payload_dir.glob("*.payload.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        video_id = payload.get("video_id") or path.name.removesuffix(".payload.json")
        base_id = short_id(video_id)
        media = payload.get("media") or {}
        transcript = payload.get("transcript") or {}
        frames = payload.get("frames") or []
        entry = {
            "video_id": video_id,
            "payload_path": str(path),
            "duration_s": media.get("duration_s", 0),
            "transcript_chars": transcript.get("chars", 0),
            "frame_count": len(frames),
            "local_media_path": (payload.get("source") or {}).get("local_media_path", ""),
        }
        index.setdefault(base_id, []).append(entry)
    return index


def build_markdown_index(markdown_dir: Path) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for path in sorted(markdown_dir.glob("TTS_short_*.md")):
        name = path.name.removeprefix("TTS_short_").removesuffix(".md")
        index.setdefault(short_id(name), []).append(str(path))
    return index


def source_card_path(source_card_dir: Path, item_id: str) -> str:
    matches = sorted(source_card_dir.glob(f"{item_id}-*.md"))
    return str(matches[0]) if matches else ""


def reconcile(manifest_path: Path, payload_dir: Path, markdown_dir: Path, source_card_dir: Path) -> dict:
    manifest = load_manifest(manifest_path)
    records = list((manifest.get("items") or {}).values())
    payload_index = build_payload_index(payload_dir)
    markdown_index = build_markdown_index(markdown_dir)
    rows = []

    for record in records:
        item_id = record.get("item_id", "")
        content_type = record.get("content_type", "unknown")
        payloads = payload_index.get(item_id, [])
        markdowns = markdown_index.get(item_id, [])
        status = "not_video"
        if content_type == "video":
            if markdowns:
                status = "done_markdown"
            elif payloads:
                status = "payload_only"
            else:
                status = "missing_payload"
        elif content_type == "article":
            status = "article_metadata_only"

        best_payload = payloads[0] if payloads else {}
        rows.append(
            {
                "item_id": item_id,
                "title": record.get("title", ""),
                "content_type": content_type,
                "status": status,
                "detail_url": record.get("detail_url", ""),
                "source_card_path": source_card_path(source_card_dir, item_id),
                "markdown_paths": markdowns,
                "payloads": payloads,
                "duration_s": best_payload.get("duration_s", 0),
                "transcript_chars": best_payload.get("transcript_chars", 0),
                "frame_count": best_payload.get("frame_count", 0),
                "download_status": record.get("download_status", ""),
                "last_error": record.get("last_error", ""),
            }
        )

    known_current = {row["item_id"] for row in rows if row["content_type"] == "video"}
    historical_only = []
    for base_id, payloads in sorted(payload_index.items()):
        if base_id in known_current:
            continue
        historical_only.append(
            {
                "item_id": base_id,
                "status": "historical_not_in_current_favorites",
                "markdown_paths": markdown_index.get(base_id, []),
                "payloads": payloads,
            }
        )

    return {
        "schema_version": "toutiao-favorites-reconcile-v1",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "manifest_path": str(manifest_path),
        "payload_dir": str(payload_dir),
        "markdown_dir": str(markdown_dir),
        "source_card_dir": str(source_card_dir),
        "summary": {
            "manifest_items": len(records),
            "current_videos": sum(1 for row in rows if row["content_type"] == "video"),
            "current_articles": sum(1 for row in rows if row["content_type"] == "article"),
            "status_counts": dict(Counter(row["status"] for row in rows)),
            "historical_payload_video_count": len(payload_index),
            "historical_markdown_video_count": len(markdown_index),
            "historical_only_count": len(historical_only),
        },
        "items": rows,
        "historical_only": historical_only,
    }


def write_markdown(report: dict, path: Path) -> None:
    summary = report["summary"]
    lines = [
        "# Toutiao Favorites Reconcile Report",
        "",
        f"- created_at: {report['created_at']}",
        f"- manifest_items: {summary['manifest_items']}",
        f"- current_videos: {summary['current_videos']}",
        f"- current_articles: {summary['current_articles']}",
        f"- historical_payload_video_count: {summary['historical_payload_video_count']}",
        f"- historical_markdown_video_count: {summary['historical_markdown_video_count']}",
        f"- historical_only_count: {summary['historical_only_count']}",
        "",
        "## Status Counts",
        "",
        "| status | count |",
        "|---|---:|",
    ]
    for status, count in sorted(summary["status_counts"].items()):
        lines.append(f"| {status} | {count} |")

    for status in ("missing_payload", "payload_only", "done_markdown", "article_metadata_only"):
        subset = [row for row in report["items"] if row["status"] == status]
        if not subset:
            continue
        lines.extend(["", f"## {status}", "", "| item_id | title | duration | transcript | markdown |", "|---|---|---:|---:|---|"])
        for row in subset:
            title = (row.get("title") or "").replace("|", "\\|")[:90]
            md = "<br>".join(row.get("markdown_paths") or [])
            lines.append(
                f"| {row['item_id']} | {title} | {row.get('duration_s', 0)} | "
                f"{row.get('transcript_chars', 0)} | {md or ''} |"
            )

    if report["historical_only"]:
        lines.extend(["", "## historical_not_in_current_favorites", "", "| item_id | markdown | payload_count |", "|---|---|---:|"])
        for row in report["historical_only"]:
            md = "<br>".join(row.get("markdown_paths") or [])
            lines.append(f"| {row['item_id']} | {md} | {len(row.get('payloads') or [])} |")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile current Toutiao favorites with historical short-video outputs")
    parser.add_argument("--manifest", type=Path, default=TOUTIAO_MANIFEST)
    parser.add_argument("--payload-dir", type=Path, default=DEFAULT_PAYLOAD_DIR)
    parser.add_argument("--markdown-dir", type=Path, default=DEFAULT_MARKDOWN_DIR)
    parser.add_argument("--source-card-dir", type=Path, default=DEFAULT_SOURCE_CARD_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--label", default="")
    args = parser.parse_args()

    report = reconcile(args.manifest, args.payload_dir, args.markdown_dir, args.source_card_dir)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    label = args.label or ts
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / f"reconcile-{label}.json"
    md_path = args.output_dir / f"reconcile-{label}.md"
    write_json(json_path, report)
    write_markdown(report, md_path)
    print(f"Reconcile JSON: {json_path}")
    print(f"Reconcile MD  : {md_path}")
    print(f"Summary       : {report['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
