# P2-6 三路对照评测 — 2026-06-04

直播内容：AI落地的胜负手（小鹅通第186回，2026-06-03）

## 对比表

| 维度 | Mac分块(Gemini) | Mac分块(Qwen) | WIN全文件(Qwen sliding-window) | 分块 vs 全文件差距 |
|------|----------------|--------------|-------------------------------|------------------|
| 正文字符数 | 9,474 | 12,917 | 17,592 | +36.2% (Qwen同模型) |
| 总文档字符数 | 52,605 | 56,047 | 154,202 | +175% |
| 末尾时间戳 | 02:33:09 | 02:33:09 | 02:33:30 | 一致 |
| 尾部20分钟覆盖 | ✅ | ✅ | ✅ | — |
| 图帧引用数 | 0 | 0 | 0 | — |
| 转录总字符 | 43,033 | 43,033 | 89,564 | +108% |
| 关键帧数 | 170 | 170 | 335 | +97% |
| body/transcript 压缩比 | 0.22 | 0.30 | 0.20 | -33% (vs Mac Qwen) |
| 分块/窗数 | 139 chunks | 139 chunks | 2 windows + 1 assembly | — |
| API 调用次数 | — | 1 | 3 | — |
| API tokens (output) | — | 7,205 | ~20,000 | +178% |
| timestamped chapters | — | 5 | 7 | +40% |
| body 尾部 gap | — | — | 30s | 几乎完美 |
| QC 警告数 | — | 1 | 2 | — |

## 关键发现

### 1. sliding-window 模式效果显著（修正前 vs 修正后）
- **修正前（one-shot，用错脚本）**: body 6,134 chars，压缩比 0.14，严重过压缩
- **修正后（sliding-window，process_replay_qwen.py）**: body 17,592 chars，压缩比 0.20，提升 +187%
- 修正后输出 tokens 从 3,451 → ~20,000，模型有足够空间展开分析

### 2. 全文件 sliding-window body 超越分块模式
WIN 全文件 Qwen body 17,592 chars 超过 Mac 分块 Qwen 12,917 chars (+36%)。全文件模式帧数翻倍（335 vs 170）且转录更完整（89K vs 43K chars），提供了更丰富的素材。

### 3. 时间戳覆盖几乎完美
body 末尾 02:33:30，流结束 02:34:00，gap 仅 30 秒（vs 分块 849 秒 gap）。

### 4. 压缩比处于临界值
body/transcript 比 0.20 刚好在阈值边界。Qwen 的全文件叙事风格更浓缩，可能因为单窗口内信息密度更高。

### 5. 图帧内联引用全部为 0
三路产物均未内联 `![](frame)` 图片引用。帧信息仅在附录的视觉证据索引中。

## 修正记录

第一次运行使用了错误脚本 `zhihuTTS_video.py`（全文件一次性 one-shot），导致 body 严重过压缩。
MAC 修复 `run_replay_qwen.bat` 后改用 `process_replay_qwen.py`（分块转写 + sliding-window 合成），结果显著改善。

| 指标 | 错误脚本 (zhihuTTS_video) | 正确脚本 (process_replay_qwen) |
|------|--------------------------|-------------------------------|
| body_chars | 6,134 | 17,592 |
| 压缩比 | 0.14 | 0.20 |
| 合成方式 | one-shot | sliding-window (2窗) |
| API 调用 | 1 | 3 |
| 转录字符 | 43,033 | 89,564 |

## 产物路径

| 路径 | 文件 |
|------|------|
| Mac分块(Gemini) | `Markdowns/TTS_0604_replay-xiaoe-20260603-gemini.md` |
| Mac分块(Qwen) | `Markdowns/TTS_0604_replay-xiaoe-20260603-qwen.md` |
| WIN全文件(Qwen) | `Markdowns/TTS_stream-local-20260603-qwen.md` |
| WIN全文件QC | `runs/stream-local-20260603-20260604-170124.qwen.final-qc.json` |

## 建议

1. **全文件 pipeline 默认走 process_replay_qwen.py**：已验证 sliding-window 模式在全文件场景下优于 one-shot，应将此设为默认。
2. **图帧内联**：当前三路均无内联图片，需要在 prompt 中强化 `![]()` 引用要求。
3. **Qwen max-frames 250 合理**：实际 2 窗口分别使用 220/155 帧，均在 cap 内。
