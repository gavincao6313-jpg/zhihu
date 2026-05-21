# 2026-05-21 直播流处理 — MAC 端需要修复的问题

## 运行概况

- 直播: 2h37min，157 个 60s chunk，SenseVoice rtf_avg ~0.055
- 至 chunk 157 正常；chunk 158 ffmpeg 切片 240s 超时退出

## Bug 1: 流结束未被代码识别（ffmpeg 超时降级）

**现象**: 进程以 `subprocess.TimeoutExpired` 退出，而非 `StreamEndedError`

**日志证据**:
```
File "zhihuTTS_stream.py", line 531, in slice_url
    completed = subprocess.run(ffmpeg_cmd, timeout=timeout)
subprocess.TimeoutExpired: Command '['ffmpeg', ..., '-t', '60.0', ...]' timed out after 240 seconds
```

**根因**:
1. `slice_url()` 中 `subprocess.run(timeout=240)` — 流断后等 4 分钟才报错
2. `is_stream_ended()` 只在 `slice_url()` 失败后才被动调用，ffmpeg 阻塞期间不检查
3. 建议: 切片 timeout 降到 30-45s；或在 ffmpeg 子进程等待期间并行轮询 DOM

**相关代码**:
- `zhihuTTS_stream.py:531` — slice_url timeout=240
- `zhihuTTS_stream.py:783,801,827` — is_stream_ended() 调用点（均在异常恢复路径）
- `stream_extractors.py:470-480` — is_stream_ended() 实现

## Bug 2: merge/build 脚本只处理最后一个时间戳的 chunk

**现象**: `merge_stream_chunks.py` 和 `build_stream_markdown.py` 均只选择了 1/157 chunk

**日志证据**:
```
[warn] 157 runs found for base 'live-20260521' — using latest: 20260521-225318
Chunks: 1
Transcript: 264 chars
Frames: 1 total
```

**根因**: `extract_run_ts()` 按每个 chunk 的完成时间戳分组，`selected_ts = max(groups.keys())` 只取最新一组

**需要**: 添加 `--all-runs` 或移除时间戳分组，所有匹配的 chunk 文件都应参与合并

**相关代码**:
- `build_stream_markdown.py:306-320`
- `merge_stream_chunks.py` 类似逻辑

## 手动补救产出

| 文件 | 大小 |
|---|---|
| 合并转录稿 (157 chunks) | 49,016 chars |
| 聚合帧 (42 slides + 192 annot) | 408 frames |
| Gemini 全量输出 | 31,768 chars (67KB) |
| Checkpoint | 715KB |

全量 Gemini 笔记: `Markdowns/TTS_stream-live-20260521-full.md`
合并转录稿: `runs/stream-live-20260521.combined-transcript.txt`
