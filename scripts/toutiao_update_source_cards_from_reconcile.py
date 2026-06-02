from __future__ import annotations

import argparse
import json
from pathlib import Path

from toutiao_common import TOUTIAO_PROBE_DIR


START = "<!-- toutiao_reconcile:start -->"
END = "<!-- toutiao_reconcile:end -->"


def latest_reconcile_report() -> Path:
    candidates = sorted(
        TOUTIAO_PROBE_DIR.glob("reconcile-*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(
            f"No reconcile-*.json found under {TOUTIAO_PROBE_DIR}. "
            "Run scripts/toutiao_reconcile_favorites.py first."
        )
    return candidates[0]


def reconcile_section(row: dict) -> str:
    lines = [
        START,
        "## 6. Reconcile Status",
        "",
        f"- Status: {row.get('status', 'unknown')}",
    ]
    markdowns = row.get("markdown_paths") or []
    if markdowns:
        for path in markdowns:
            lines.append(f"- Existing Markdown: {path}")
    payloads = row.get("payloads") or []
    if payloads:
        for payload in payloads:
            lines.append(f"- Payload: {payload.get('payload_path', '')}")
            lines.append(f"- Duration: {payload.get('duration_s', 0)}")
            lines.append(f"- Transcript chars: {payload.get('transcript_chars', 0)}")
            lines.append(f"- Frames: {payload.get('frame_count', 0)}")
    if row.get("status") == "missing_payload":
        lines.append("- Action: media acquisition required before ASR or Qwen synthesis.")
    elif row.get("status") == "payload_only":
        lines.append("- Action: reuse existing payload and rerun split/retry synthesis; do not redownload media first.")
    elif row.get("status") == "done_markdown":
        lines.append("- Action: reuse existing Markdown; do not reprocess unless source changed intentionally.")
    elif row.get("status") == "article_metadata_only":
        lines.append("- Action: keep as article metadata card unless a real web URL is available.")
    lines.extend(["", END, ""])
    return "\n".join(lines)


def replace_section(text: str, section: str) -> str:
    if START in text and END in text:
        before = text.split(START, 1)[0].rstrip()
        after = text.split(END, 1)[1].lstrip()
        return before + "\n\n" + section + ("\n" + after if after else "")
    return text.rstrip() + "\n\n" + section


def main() -> int:
    parser = argparse.ArgumentParser(description="Write reconcile status sections into Toutiao source-cards")
    parser.add_argument("--reconcile-json", type=Path, default=None)
    args = parser.parse_args()

    report_path = args.reconcile_json or latest_reconcile_report()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    updated = 0
    missing_cards = 0
    for row in report.get("items") or []:
        card_path = row.get("source_card_path") or ""
        if not card_path:
            missing_cards += 1
            continue
        path = Path(card_path)
        if not path.exists():
            missing_cards += 1
            continue
        text = path.read_text(encoding="utf-8")
        path.write_text(replace_section(text, reconcile_section(row)), encoding="utf-8")
        updated += 1

    print(f"Reconcile report: {report_path}")
    print(f"Cards updated   : {updated}")
    print(f"Missing cards   : {missing_cards}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
