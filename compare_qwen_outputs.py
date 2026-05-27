"""
Compare QWEN replay synthesis vs last night's live baseline.

Usage after both outputs exist:
    python compare_qwen_outputs.py [replay_md] [baseline_md]
"""
import argparse
import io
import re
import sys
from pathlib import Path

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


def count_sections(text: str) -> int:
    return len(re.findall(r'^###\s+\[', text, re.MULTILINE))


def count_code_blocks(text: str) -> int:
    return len(re.findall(r'```', text)) // 2


def count_glossary_terms(text: str) -> int:
    m = re.search(r'## 2\.\s*核心知识字典.*?\n(.*?)(?=##\s|\Z)', text, re.DOTALL)
    if not m:
        return 0
    return len(re.findall(r'^\d+\.\s+\*\*', m.group(1), re.MULTILINE))


def extract_qc(text: str) -> dict:
    qc = {}
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("> -"):
            key_val = line.replace("> -", "").strip()
            if ":" in key_val:
                k, v = key_val.split(":", 1)
                qc[k.strip()] = v.strip()
            elif "|" in key_val:
                # Parse pipe-separated key: value pairs
                pass
    return qc


def extract_title(text: str) -> str:
    m = re.search(r'^#\s+(.+)$', text, re.MULTILINE)
    return m.group(1).strip() if m else "(no title)"


def body_char_count(text: str) -> int:
    """Count chars in the body (between H1 title and appendices)."""
    # Remove QC header
    body = re.sub(r'^>.*?(?=^#\s)', '', text, flags=re.DOTALL | re.MULTILINE)
    # Stop at 确定性附录
    body = re.split(r'##\s+\d+\.\s*确定性附录', body)[0]
    return len(body.strip())


def word_count(text: str) -> int:
    """Chinese character count (excluding spaces, punctuation)."""
    return len(re.findall(r'[一-鿿㐀-䶿]', text))


def report(name: str, path: Path):
    text = path.read_text(encoding="utf-8")
    qc = extract_qc(text)
    title = extract_title(text)
    sections = count_sections(text)
    code_blocks = count_code_blocks(text)
    glossary = count_glossary_terms(text)
    body_chars = body_char_count(text)
    cjk_chars = word_count(text)
    total_chars = len(text)

    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    print(f"  Title:        {title}")
    print(f"  Total chars:  {total_chars:,}")
    print(f"  Body chars:   {body_chars:,}")
    print(f"  CJK chars:    {cjk_chars:,}")
    print(f"  H3 sections:  {sections}")
    print(f"  Code blocks:  {code_blocks}")
    print(f"  Glossary:     {glossary} terms")
    if qc:
        print(f"  QC:")
        for k, v in qc.items():
            print(f"    {k}: {v}")
    return {
        "title": title,
        "total_chars": total_chars,
        "body_chars": body_chars,
        "cjk_chars": cjk_chars,
        "sections": sections,
        "code_blocks": code_blocks,
        "glossary": glossary,
        "qc": qc,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("replay", nargs="?", default="Markdowns/TTS_stream-replay-20260527-qwen-qwen-replay.md")
    ap.add_argument("baseline", nargs="?", default="runs/baseline-live-ab-20260526-qwen-sw.md")
    ap.add_argument("--gemini-baseline", default="runs/baseline-live-ab-20260526-gemini.md")
    ap.add_argument("--include-gemini", action="store_true", help="Also show Gemini baseline")
    args = ap.parse_args()

    replay_path = Path(args.replay)
    baseline_path = Path(args.baseline)
    gemini_path = Path(args.gemini_baseline)

    if not baseline_path.exists():
        print(f"Baseline not found: {baseline_path}", file=sys.stderr)
        sys.exit(1)

    print("Comparing QWEN outputs...")
    print(f"  Baseline: {baseline_path}")
    print(f"  Replay:   {replay_path}")
    if args.include_gemini and gemini_path.exists():
        print(f"  Gemini:   {gemini_path}")

    baseline_stats = report("BASELINE: QWEN sliding-window (last night live)", baseline_path)

    if replay_path.exists():
        replay_stats = report("REPLAY: QWEN sliding-window (replay video)", replay_path)

        print(f"\n{'='*60}")
        print(f"  COMPARISON")
        print(f"{'='*60}")

        diffs = []
        for key in ["total_chars", "body_chars", "cjk_chars", "sections", "code_blocks", "glossary"]:
            b = baseline_stats[key]
            r = replay_stats[key]
            delta = r - b
            pct = (delta / b * 100) if b else 0
            direction = "+" if delta > 0 else ""
            diffs.append(f"  {key:20s}: {b:>8,} → {r:>8,}  ({direction}{delta:+,}  {direction}{pct:+.1f}%)")

        print("\n".join(diffs))

        # Check for QC warnings
        b_qc = baseline_stats.get("qc", {})
        r_qc = replay_stats.get("qc", {})
        if any("qwen_overcompressed" in k for k in b_qc):
            print(f"\n  [FIXED?] Baseline had overcompression warning")
            if not any("qwen_overcompressed" in k for k in r_qc):
                print(f"  Yes - replay output no longer shows overcompression!")
            else:
                print(f"  Still present in replay output")
    else:
        print(f"\nReplay output not found yet: {replay_path}")
        print("Waiting for QWEN synthesis to complete...")

    if args.include_gemini and gemini_path.exists():
        report("GEMINI baseline (last night live)", gemini_path)


if __name__ == "__main__":
    main()
