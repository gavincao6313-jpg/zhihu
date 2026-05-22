## WIN 端 2026-05-22 直播 bug 证据

### 运行环境
- 分支: `feature/stream-transcript-validation`（cherry-pick 了 main 的 `7615267`、`ad2deb1`、`07e46b7`）
- 直播: 105 chunks, 1h45m, 37,749 chars transcript, 335 frames
- 采集+merge 正常，Gemini 合成阶段连续发现 2 个 bug

---

### Bug 1: `utils.py` 缺失 → `ModuleNotFoundError`

**现象（BAT 输出）：**
```
Traceback (most recent call last):
  File "scripts\build_stream_markdown.py", line 39, in <module>
    from utils import call_gemini, extract_run_ts, fmt_ts
ModuleNotFoundError: No module named 'utils'
```

**根因：** `utils.py` 在 commit `39dd0c9` 创建，但该 commit 不在 `feature/stream-transcript-validation` 分支上。commit `7615267` 的 `build_stream_markdown.py` 引入了 `from utils import ...`，但 cherry-pick 时 `utils.py` 不会跟过来（它在更早的 commit 里）。

**WIN 端临时修复：** 手动从 `origin/main` 提取 `utils.py` 放到项目根目录。

**建议修复：** `7615267` 应该在 commit message 里注明依赖 `39dd0c9` 的 `utils.py`，或者把 `utils.py` 的创建合并在同一个 commit 里。或者把 `call_gemini` / `fmt_ts` / `extract_run_ts` 保留为 `build_stream_markdown.py` 的内部函数（`live_sectioned_synthesis.py` 如果也用到，可以 duplicate 或放回 inline）。

---

### Bug 2: chunk 分组逻辑导致只用 1/105 chunk

**现象（修复前的手动运行输出）：**
```
[warn] 105 runs for '1' — using: 20260522-215812
Chunks   : 1 (run: 20260522-215812)
Transcript: 320 chars       ← 应该是 37,749
Frames    : 2 total          ← 应该是 335
```

**根因：** `build_stream_markdown.py:400-414` 用 `extract_run_ts()` 对 chunk 分组。每个 chunk 文件名包含各自的完成时间戳（如 `-20260522-200049`），导致 105 个 chunk 被分到 105 个不同的组，每组 1 个文件。`max(groups.keys())` 取最新时间戳组 → 只拿到 1 个 chunk。

```python
# 原代码（bug）
groups: dict[str, list[Path]] = defaultdict(list)
for f in all_found:
    groups[extract_run_ts(f)].append(f)      # 105个chunk → 105个组
selected_ts = args.run_ts if args.run_ts else max(groups.keys())
chunk_files = sorted(groups[selected_ts], ...)  # 只取1个chunk
```

**WIN 端临时修复（`build_stream_markdown.py` diff）：**
```python
# 修复：不传 --run-ts 时使用全部 chunk
if args.run_ts:
    chunk_files = [f for f in all_found if extract_run_ts(f) == args.run_ts]
    ...
    selected_ts = args.run_ts
else:
    chunk_files = all_found   # 全部105个
    selected_ts = extract_run_ts(sorted(chunk_files, key=parse_chunk_start)[-1])
```

**建议修复：** `extract_run_ts` 的设计假设同一批 chunk 共享同一个 run timestamp，但实际每个 chunk 有独立的完成时间戳。要么按 chunk start_s 分组，要么默认不过滤直接用全部文件。

---

### Bug 3 (minor): `merge_stream_chunks.py` SyntaxWarning

```
D:\zhihu\zhihu_url\scripts\merge_stream_chunks.py:9: SyntaxWarning: invalid escape sequence '\m'
  python scripts\merge_stream_chunks.py --base ...
```

line 9 的 docstring 里 `\m` 被当作转义序列。改 raw string 或换 forward slash 即可。

---

### 修复后的最终运行结果

```
Chunks   : 105
Transcript: 37,749 chars
Frames    : 335 total
QC manifest : runs\stream-1-20260522-215812.final-qc.json  [full]
  Gemini parts: transcript 37,749 chars, 335/335 frames (slide=31, annot=176)
[1] Sending to Gemini (672 parts)...
[1] Done: 15,950 chars, 1 calls
NotebookLM document : Markdowns\TTS_stream-1.md (16,146 chars)
```

产物：
- `Markdowns/TTS_stream-1.md` — 35KB, QC header `> **Live Final QC**`, source_status: full
- `runs/stream-1-merged.md` — 106KB, 31 sections
- `runs/stream-1-...final-qc.json` — 0 gaps, 0 warnings
