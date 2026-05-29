from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from toutiao_common import TOUTIAO_PROBE_DIR, write_json


def load_reconcile(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_duration(value: str | int | float | None) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return 0
    if text.isdigit():
        return int(text)
    parts = text.split(":")
    if not all(part.isdigit() for part in parts):
        return 0
    total = 0
    for part in parts:
        total = total * 60 + int(part)
    return total


def load_classify_index(path: Path | None) -> dict[str, dict]:
    if not path:
        return {}
    report = json.loads(path.read_text(encoding="utf-8"))
    return {item.get("item_id", ""): item for item in report.get("items", []) if item.get("item_id")}


def item_sort_key(item: dict) -> tuple[int, str]:
    duration = item.get("duration_s") or 0
    return (-int(duration), item.get("item_id", ""))


def metadata_duration(item: dict, classify_index: dict[str, dict]) -> tuple[int, str]:
    duration = parse_duration(item.get("duration_s"))
    if duration:
        return duration, "reconcile_payload"
    classify_item = classify_index.get(item.get("item_id", ""))
    raw_fields = classify_item.get("raw_json_fields") or {}
    duration = parse_duration(raw_fields.get("video_duration_str"))
    if duration:
        return duration, "classify_raw_json_fields.video_duration_str"
    return 0, ""


def build_queue(reconcile: dict, classify_index: dict[str, dict] | None = None, status: str = "missing_payload") -> dict:
    classify_index = classify_index or {}
    items = [item for item in reconcile.get("items", []) if item.get("status") == status]
    for item in items:
        duration, duration_source = metadata_duration(item, classify_index)
        item["duration_s"] = duration
        item["duration_source"] = duration_source
    items = sorted(items, key=item_sort_key)
    queue_items = []
    for index, item in enumerate(items, start=1):
        queue_items.append(
            {
                "rank": index,
                "item_id": item.get("item_id", ""),
                "title": item.get("title", ""),
                "detail_url": item.get("detail_url", ""),
                "source_card_path": item.get("source_card_path", ""),
                "download_status": item.get("download_status", ""),
                "last_error": item.get("last_error", ""),
                "duration_s": item.get("duration_s", 0),
                "duration_source": item.get("duration_source", ""),
                "priority": classify_priority(item),
                "next_action": next_action(item),
            }
        )
    return {
        "schema_version": "toutiao-missing-payload-queue-v1",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_reconcile_path": reconcile.get("_source_path", ""),
        "status": status,
        "summary": {
            "queue_count": len(queue_items),
            "failed_download_count": sum(1 for item in queue_items if item.get("download_status") == "failed"),
            "pending_download_count": sum(1 for item in queue_items if item.get("download_status") == "pending"),
        },
        "items": queue_items,
    }


def classify_priority(item: dict) -> str:
    duration = int(item.get("duration_s") or 0)
    if item.get("download_status") == "failed":
        return "P0_failed_download"
    if duration >= 1800:
        return "P1_long_high_value"
    if duration <= 180:
        return "P2_short_quick_probe"
    return "P3_standard_probe"


def next_action(item: dict) -> str:
    if item.get("download_status") == "failed":
        return "Inspect app-gated Ixigua/Toutiao media acquisition; do not bulk retry with current downloader."
    return "Try targeted media acquisition or request/export source MP4; then run short-video preprocess."


def format_duration(seconds: int | float | None) -> str:
    total = int(seconds or 0)
    minutes, sec = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def write_markdown(queue: dict, path: Path) -> None:
    summary = queue["summary"]
    lines = [
        "# Toutiao Missing Payload Queue",
        "",
        f"- created_at: {queue['created_at']}",
        f"- source_reconcile_path: {queue.get('source_reconcile_path', '')}",
        f"- queue_count: {summary['queue_count']}",
        f"- failed_download_count: {summary['failed_download_count']}",
        f"- pending_download_count: {summary['pending_download_count']}",
        "",
        "| rank | priority | item_id | duration | status | title | next_action |",
        "|---:|---|---|---:|---|---|---|",
    ]
    for item in queue["items"]:
        title = (item.get("title") or "").replace("|", "\\|")[:90]
        action = item.get("next_action", "").replace("|", "\\|")
        lines.append(
            f"| {item['rank']} | {item['priority']} | {item['item_id']} | "
            f"{format_duration(item.get('duration_s'))} | {item.get('download_status', '')} | "
            f"{title} | {action} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_url_list(queue: dict, path: Path) -> None:
    lines = []
    for item in queue["items"]:
        url = item.get("detail_url") or ""
        if url:
            lines.append(url)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export current Toutiao missing-payload items as an isolated work queue")
    parser.add_argument("--reconcile-json", type=Path, required=True)
    parser.add_argument("--classify-json", type=Path)
    parser.add_argument("--output-dir", type=Path, default=TOUTIAO_PROBE_DIR)
    parser.add_argument("--label", default="")
    args = parser.parse_args()

    reconcile = load_reconcile(args.reconcile_json)
    reconcile["_source_path"] = str(args.reconcile_json)
    classify_index = load_classify_index(args.classify_json)
    queue = build_queue(reconcile, classify_index=classify_index)

    label = args.label or datetime.now().strftime("%Y%m%dT%H%M%S")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / f"missing-payload-queue-{label}.json"
    md_path = args.output_dir / f"missing-payload-queue-{label}.md"
    urls_path = args.output_dir / f"missing-payload-queue-{label}.urls.txt"

    write_json(json_path, queue)
    write_markdown(queue, md_path)
    write_url_list(queue, urls_path)

    print(f"Missing payload queue JSON: {json_path}")
    print(f"Missing payload queue MD  : {md_path}")
    print(f"Missing payload URL list  : {urls_path}")
    print(f"Summary                   : {queue['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
