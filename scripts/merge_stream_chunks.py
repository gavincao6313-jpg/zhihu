"""
Merge stream chunk global transcripts into a structured Markdown document.

Reads per-chunk global-transcript.txt and payload.json from runs/, groups sentences
into semantic sections at slide-change keyframe boundaries, and writes a single
structured Markdown file — matching the format of replay-20260518-final.md.

Usage (Windows):
    python scripts\merge_stream_chunks.py --base zhihu-gaowei-agent-20260518

Usage (Mac/Linux):
    python scripts/merge_stream_chunks.py --base zhihu-gaowei-agent-20260518

Options:
    --base       Stream base name (required). Matches files: stream-{base}_chunk*.global-transcript.txt
    --runs-dir   Directory containing chunk files (default: runs)
    --out        Output .md path (default: runs/stream-{base}-merged.md)
"""
import argparse, json, re, sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils import extract_run_ts, fmt_ts


def parse_chunk_start(path: Path) -> int:
    """Extract start_s from filename like stream-base_chunkXXX_1234s-timestamp.ext"""
    m = re.search(r'_chunk\d+_(\d+)s[-.]', path.name)
    return int(m.group(1)) if m else 0


def parse_timestamp(ts_str: str) -> float:
    """Parse HH:MM:SS → seconds."""
    parts = ts_str.strip().split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    return 0.0


def load_chunk_lines(path: Path) -> list[tuple[float, str]]:
    """Read a global-transcript.txt and return (timestamp_s, text) pairs."""
    result = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        # Formats emitted by offset_transcript_text:
        #   [HH:MM:SS] text
        #   [HH:MM:SS - HH:MM:SS] text
        m = re.match(r'^\[(\d+:\d+:\d+)(?:\s*-\s*\d+:\d+:\d+)?\]\s+(.*)', line)
        if m:
            result.append((parse_timestamp(m.group(1)), m.group(2).strip()))
    return result


def load_chunk_slides(payload_path: Path, chunk_start_s: int) -> list[float]:
    """Return slide event timestamps (global seconds) from a chunk payload.json."""
    if not payload_path.exists():
        return []
    with open(payload_path, encoding="utf-8") as f:
        payload = json.load(f)
    slides = []
    for e in payload.get("events", []):
        if e.get("type") == "slide":
            slides.append(chunk_start_s + float(e.get("frame_idx", 0)))
    return slides


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base",     required=True,  help="Stream base name")
    ap.add_argument("--runs-dir", default="runs", help="Directory with chunk files")
    ap.add_argument("--out",      default=None,   help="Output markdown path")
    ap.add_argument("--run-ts",   default=None,   help="Use specific run timestamp YYYYMMDD-HHMMSS (default: latest)")
    args = ap.parse_args()

    runs_dir = Path(args.runs_dir)
    pattern  = f"stream-{args.base}_chunk*.global-transcript.txt"
    all_found = list(runs_dir.glob(pattern))

    if not all_found:
        print(f"ERROR: no files matching {runs_dir / pattern}", file=sys.stderr)
        sys.exit(1)

    # Group by run timestamp to avoid merging chunks from multiple runs with the same base name
    groups: dict[str, list[Path]] = defaultdict(list)
    for f in all_found:
        groups[extract_run_ts(f)].append(f)

    if args.run_ts:
        if args.run_ts not in groups:
            print(f"ERROR: run-ts '{args.run_ts}' not found. Available: {sorted(groups)}", file=sys.stderr)
            sys.exit(1)
        selected_ts = args.run_ts
    else:
        selected_ts = max(groups.keys())

    if len(groups) > 1:
        print(f"[warn] {len(groups)} runs found for base '{args.base}' — using latest: {selected_ts}")
        for ts in sorted(groups.keys()):
            marker = " ← selected" if ts == selected_ts else ""
            print(f"  {ts}: {len(groups[ts])} chunks{marker}")

    chunk_files = sorted(groups[selected_ts], key=parse_chunk_start)
    print(f"Found {len(chunk_files)} chunks in {runs_dir} (run: {selected_ts})")

    # Collect all sentences and all slide times across chunks
    all_sentences: list[tuple[float, str]] = []
    all_slides:    list[float]             = []

    for cf in chunk_files:
        chunk_start_s  = parse_chunk_start(cf)
        all_sentences += load_chunk_lines(cf)

        payload_stem = cf.name.replace(".global-transcript.txt", ".payload.json")
        all_slides   += load_chunk_slides(cf.parent / payload_stem, chunk_start_s)

    if not all_sentences:
        print("ERROR: no sentences found in chunk files", file=sys.stderr)
        sys.exit(1)

    all_slides = sorted(set(all_slides))
    total_chars     = sum(len(s) for _, s in all_sentences)
    total_duration  = all_sentences[-1][0]

    # Build structured Markdown
    out: list[str] = [
        "# 知乎直播 — 流转写合并文档",
        "",
        "| 属性 | 值 |",
        "|---|---|",
        f"| 直播基础名 | {args.base} |",
        f"| 分片数 | {len(chunk_files)} |",
        f"| 句子数 | {len(all_sentences):,} |",
        f"| 总字符数 | {total_chars:,} |",
        f"| 幻灯片切换 | {len(all_slides)} 次 |",
        f"| 覆盖时长 | {fmt_ts(total_duration)} |",
        "",
        "---",
        "",
    ]

    slide_idx   = 0
    section_num = 1
    out += [f"## 第 {section_num} 部分 — {fmt_ts(0)}", ""]

    buf: list[str] = []
    for ts, sent in all_sentences:
        while slide_idx < len(all_slides) and ts >= all_slides[slide_idx]:
            out.extend(buf)
            buf = []
            section_num += 1
            slide_ts = all_slides[slide_idx]
            out += ["", "---", "", f"## 第 {section_num} 部分 — {fmt_ts(slide_ts)}", ""]
            slide_idx += 1

        buf.append(f"> [{fmt_ts(ts)}] {sent}")

    out.extend(buf)

    out += [
        "",
        "---",
        "",
        "## 合并统计",
        "",
        f"- **分片数**: {len(chunk_files)}",
        f"- **句子数**: {len(all_sentences):,}",
        f"- **总字符数**: {total_chars:,}",
        f"- **幻灯片切换**: {len(all_slides)} 次",
        f"- **章节数**: {section_num}",
        f"- **覆盖时长**: {fmt_ts(total_duration)}",
        "",
    ]

    out_path = Path(args.out) if args.out else runs_dir / f"stream-{args.base}-merged.md"
    out_path.write_text("\n".join(out), encoding="utf-8")
    print(f"Written: {out_path}")
    print(f"Sections: {section_num}  Sentences: {len(all_sentences)}  Slides: {len(all_slides)}")


if __name__ == "__main__":
    main()
