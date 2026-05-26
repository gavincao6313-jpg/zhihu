# Bug Report — 2026-05-26 A/B Test Run

## Bug 1 [CRITICAL — FIXED]: `--cleanup-slices` 删除所有输出文件

**文件**: `zhihuTTS_stream.py` 第 767-769 行（已删除）

**错误代码**:
```python
if args.cleanup_slices:
    for _p in (transcript_path, global_transcript_path, payload_path, report_path):
        _p.unlink(missing_ok=True)
```

**根因**: `--cleanup-slices` 本意是 "clean up slices"（删除临时 MP4 切片），但错误地连带删除了所有输出产物（逐字稿、global-transcript、payload、report）。

MP4 切片的清理已在第 725 行正确执行：`segment_path.unlink(missing_ok=True)`。第 767-769 行的额外清理是多余的，导致：
- 合并步骤（merge）失败：FileNotFoundError 找不到 global-transcript 文件
- Payload JSON 数据不可恢复（checkpoint 不缓存 payload）
- 186 个 chunk 的输出全部丢失

**修复**: 删除整个 3 行代码块。`--cleanup-slices` 现在仅删除临时 MP4 切片（第 725 行）。

**证据文件**:
- 修复前 manifest: `runs\stream-replay-ab-20260526-20260526-142504.manifest.md`（显示 "unrecoverable slice error at chunk 1"，covered duration 仅 3 分钟）
- 恢复后的 checkpoint: `runs\stream-replay-ab-20260526.checkpoint.json`（186 chunks，从 checkpoint 提取 global_transcript_text 恢复）
- 缺失的 payload 文件导致 0 frames 合成

---

## Bug 2 [MEDIUM]: QWEN provider 缺少 `openai` 依赖

**文件**: `requirements.txt`

**现象**: QWEN 合成时报错 `openai not installed`

**根因**: `openai>=1.0.0` 虽然已添加到 `requirements.txt`，但 `run_zhihu_live.bat` 和 `zhihuTTS_stream.py` 不会自动 `pip install`。Windows 环境下需要手动安装。

**建议**: 在 `run_zhihu_live.bat` 的 provider 切换逻辑中添加依赖检查，或在 README 中明确标注。

---

## Bug 3 [LOW]: Gemini 3.5 Flash 503 高负载

**现象**: Gemini 合成时首次调用返回 503 UNAVAILABLE，65 秒后重试成功。

**模型**: `gemini-3.5-flash`

**影响**: 导致合成需要 2 次 API 调用而非 1 次，增加延迟和 token 消耗。

**建议**: 考虑增加初始 backoff 或使用 `gemini-2.5-flash` 作为回退方案。

---

## A/B Test Summary

| | Gemini 3.5 Flash | QWEN 3.6 Flash |
|---|---|---|
| 模型输出 | 9,794 chars | 9,565 chars |
| API 调用 | 2（含 503 重试） | 1 |
| 质量 | 优秀（格式化更精细） | 优秀（无错误，更简洁） |
| 输出文件 | `Markdowns\TTS_stream-replay-ab-20260526-gemini35.md` | `Markdowns\TTS_stream-replay-ab-20260526-qwen.md` |

**结论**: 两个模型质量相当，QWEN 可靠性更好（无 503）。建议默认使用 QWEN，Gemini 作为备选。
