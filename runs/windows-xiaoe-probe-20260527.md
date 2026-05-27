# 小鹅通 (xiaoe) 新直播源探测 — 2026-05-27

## 背景

zhihu CC (csslcloud.net) 直播源已替换为小鹅通平台 (xet.pomoho.com)。本批次验证新源的全链路兼容性。

## 新平台特征

- **平台**：小鹅通 (xiaoe)，HLS 流基于腾讯云 VOD
- **m3u8**：`confusion_index` 加密 m3u8，TS 分片经过混淆
- **CDN**：`*.vod2.myqcloud.com`，下载需携带 session cookie + Referer
- **Auth**：Playwright 拦截浏览器 response 获取 m3u8 内容，用 requests.Session 带 cookie 下载 TS 分片
- **视频**：1920x1080, H.264 15fps, AAC 44.1kHz stereo, 02:12:38 (7959s), 988 MB

## 处理结果

### 下载
- 工具：`download_xiaoe_replay.py`（Playwright 拦截 m3u8 → 解析 1602 个 TS 分片 → 逐片下载 → ffmpeg concat）
- 输出：`Videos/replay-xiaoe.mp4`（988 MB）

### 转写 + 合成对比

| 指标 | QWEN (qwen3.6-flash) | Gemini 3.5 Flash |
|------|---------------------|-------------------|
| 策略 | sliding-window (2 windows + assembly) | one-shot |
| API 调用 | 3 | 1 |
| 帧数 | 143 | 143 |
| 输出大小 | 73,667 chars | 75,192 chars |
| body coverage | **360s gap** (截止 02:07:00) | **22s gap** (近完整) |

### 产物

- `Markdowns/TTS_stream-replay-xiaoe-20260527-qwen-qwen.md`
- `Markdowns/TTS_stream-replay-xiaoe-20260527-qwen-gemini35.md`
- `runs/stream-replay-xiaoe-20260527-qwen-20260527-123906.manifest.json`
- `runs/stream-replay-xiaoe-20260527-qwen-20260527-123906.qwen.final-qc.json`
- `runs/stream-replay-xiaoe-20260527-qwen-20260527-123906.gemini35.final-qc.json`
- `runs/stream-replay-xiaoe-20260527-qwen-20260527-123906.combined-transcript.txt`

## MAC 端待分析

1. **QWEN body coverage 360s gap**：sliding-window final assembly 丢失最后 ~6 分钟。是对比 prompt 截断还是 window 覆盖不足？
2. **新平台适配**：`download_xiaoe_replay.py` 目前是独立探测脚本，是否需要集成到主流程 `zhihuTTS_stream.py`？
3. **Gemini one-shot 优势**：单次调用、覆盖率更好、更省配额。小鹅通回放是否默认走 Gemini one-shot？
4. **小鹅通直播流**：回放验证通过，直播 HLS 抓取是否同样可行？需要实际直播验证。
