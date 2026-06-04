"""hybrid_final.py — Qwen window notes → Gemini final synthesis.

Reads window notes produced by a previous Qwen sliding-window run, then
calls Gemini once to produce the final NotebookLM document.

Usage (run AFTER build_stream_markdown.py --provider qwen --synthesis-pass sliding-window):
    python scripts/hybrid_final.py --base zhihu-20260604 [--runs-dir runs] [--markdowns-dir Markdowns]

Output:
    Markdowns/TTS_stream-{base}-hybrid.md
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_HYBRID_PROMPT = """
# 角色与目标
你是一位资深 AI 应用研究员，负责将多个窗口级保真笔记整合为一份高质量的 NotebookLM 知识库文档。
这些笔记来自对一场中文 AI 技术直播的逐段分析，按时间顺序排列。你的任务是在不压缩细节的前提下，组装成结构清晰、细节完整、可检索的 Markdown 文档。

# 关键规则
- 不得将窗口笔记压缩成摘要，必须展开所有技术细节、数字、案例和 Prompt。
- 保留所有代码块、Prompt、配置和命令，每段必须用三反引号 ``` 包裹。
- 章节按真实时间线线性排列，时间段不重叠。
- Glossary 5-10 个核心概念，定义精准且保留细节。
- 每章叙事不少于 200 字；不得用 bullet 替代段落展开。

# 必须输出的结构
# （准确具体的中文标题，覆盖核心技术内容，不以受众身份为主题）

## 1. 视频元数据
- **推测主题：**
- **核心关键词：**
- **直播时长：**

## 2. 核心知识字典（Glossary）

## 3. 详尽内容解析
### [HH:MM:SS - HH:MM:SS] 章节标题
- **核心论点：**
- **详细展开：**（不少于 200 字）
- **视觉/屏幕内容：**
- **重要金句：**

## 4. 遗留问题与下一步行动

## 5. 技术资产附录：Prompts / Code / Config
集中保留所有 Prompt、代码块、配置。每段必须用 ``` 包裹，标注来源时间。

## 6. 关键事实索引
列出所有数字、比例、工具名、模型名、评分。每条标注来源时间段。

# 自检（输出前确认）
H1 存在；章节时间线不重叠；技术资产附录有 ``` 围栏代码块；关键事实索引存在；正文不是短摘要。
"""


def find_manifest(runs_dir: Path, base: str) -> Path | None:
    candidates = sorted(
        runs_dir.glob(f"stream-{base}-*.manifest.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def load_window_notes(manifest: dict, runs_dir: Path) -> list[str]:
    note_paths = manifest.get("qwen_window_notes", [])
    notes: list[str] = []
    for p in note_paths:
        path = Path(p)
        if not path.is_absolute():
            path = runs_dir / path
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                text = data.get("text", "")
            except (json.JSONDecodeError, KeyError):
                text = path.read_text(encoding="utf-8")
            if text.strip():
                notes.append(text.strip())
    return notes


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base",              required=True)
    ap.add_argument("--runs-dir",          default="runs")
    ap.add_argument("--markdowns-dir",     default="Markdowns")
    ap.add_argument("--model",             default=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"))
    ap.add_argument("--max-retries",       type=int, default=4)
    ap.add_argument("--max-continuations", type=int, default=6)
    args = ap.parse_args()

    runs_dir      = Path(args.runs_dir)
    markdowns_dir = Path(args.markdowns_dir)
    markdowns_dir.mkdir(parents=True, exist_ok=True)

    api_key = (
        os.environ.get("OPENCLAW_GOOGLE_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
    )
    if not api_key:
        print("[错误] 请设置 GEMINI_API_KEY 或 OPENCLAW_GOOGLE_API_KEY", file=sys.stderr)
        sys.exit(1)

    manifest_path = find_manifest(runs_dir, args.base)
    if not manifest_path:
        print(f"[错误] 未找到 runs/stream-{args.base}-*.manifest.json", file=sys.stderr)
        print("请先运行: python scripts/build_stream_markdown.py --base ... --provider qwen "
              "--synthesis-pass sliding-window", file=sys.stderr)
        sys.exit(1)

    manifest     = json.loads(manifest_path.read_text(encoding="utf-8"))
    window_notes = load_window_notes(manifest, runs_dir)

    if not window_notes:
        print("[错误] manifest 中无 qwen_window_notes，或文件不存在", file=sys.stderr)
        print(f"  manifest: {manifest_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Base        : {args.base}")
    print(f"Manifest    : {manifest_path.name}")
    print(f"Window notes: {len(window_notes)} loaded")
    print(f"Gemini model: {args.model}")

    combined_notes = "\n\n---\n\n".join(
        f"<!-- window {i + 1}/{len(window_notes)} -->\n{text}"
        for i, text in enumerate(window_notes)
    )

    from utils import call_gemini
    try:
        from google import genai
    except ImportError:
        print("[錯誤] google-genai not installed — pip install google-genai", file=sys.stderr)
        sys.exit(1)

    client = genai.Client(api_key=api_key)
    parts  = [_HYBRID_PROMPT.strip(), combined_notes]

    print(f"\n=== Gemini hybrid synthesis ({len(window_notes)} windows → 1 Gemini call) ===")
    result_text = call_gemini(
        client, parts, f"{args.base}-hybrid",
        model=args.model,
        max_retries=args.max_retries,
        max_continuations=args.max_continuations,
    )

    if not result_text:
        print("[错误] Gemini 返回空文本", file=sys.stderr)
        sys.exit(1)

    out_path = markdowns_dir / f"TTS_stream-{args.base}-hybrid.md"
    out_path.write_text(result_text, encoding="utf-8")
    print(f"\n完成: {out_path}  ({len(result_text):,} chars)")


if __name__ == "__main__":
    main()
