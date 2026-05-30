# 回放视频 Qwen 合成路径缺失 — WIN 验证发现

**日期：** 2026-05-30  
**提交给：** MAC  
**优先级：** 中（不影响直播流，但回放验证受阻）

---

## 背景

为验证 MAC 的 sliding-window overlap 修复，使用独立 MP4 回放视频（vzuu.com, 268MB, 160min）走完整管线：下载 → 帧提取 → 转写 → Qwen 合成。

验证过程中发现回放视频 → Qwen 合成路径存在以下缺口。

---

## 问题 1：缺少 payload → chunk 标准转换

**现象：**
`zhihuTTS_video.py` 产出一个 `payload.json`（含 full_text + frames），但 `build_stream_markdown.py` 需要 `stream-{base}_chunk*.global-transcript.txt` + `payload.json` 格式。

**当前状态：**
临时写了 `scripts/convert_payload_to_chunks.py` 做桥接（单 chunk 覆盖全时长），但存在以下局限：
- 单 chunk 导致 `timeline_end` 计算错误（显示 00:01:01 而非实际 02:38:10）
- `body_coverage` gap 为负数

**建议修复：**
- 在 `build_stream_markdown.py` 增加 `--payload` 参数，直接接受 `zhihuTTS_video.py` 产出的 payload.json 格式
- 或让 `zhihuTTS_video.py` 直接产出 stream chunk 格式

---

## 问题 2：帧 marker 格式不一致

**现象：**
`zhihuTTS_video.py` 的帧 marker 不含 `type=slide` / `type=annotation` 标记，导致 `build_stream_markdown.py` 的 `_frame_type()` 函数将全部帧归类为 `context`：

```
slide=0, annot=0  (实际应有 slide=65, annot=251)
```

**影响：**
- 滑动窗口的 `_frame_type_counts` 统计失真
- 幻灯片优先选择逻辑（slide frames 优先保留）失效
- 所有帧被等同对待，可能降低关键幻灯片帧的保留率

**建议修复：**
统一 `zhihuTTS_video.py` 和 `zhihuTTS_stream.py` 的帧 marker 格式。

---

## 问题 3：回放管线无 Qwen 支持

**现象：**
- `run_single_file.py` 硬编码 Gemini（`from google import genai`）
- `zhihuTTS_video.py` 的 `build_gemini_payload()` 只产出 Gemini 格式
- 回放视频 → Qwen 合成无标准入口

**建议修复：**
- `run_single_file.py` 支持 `--provider qwen` 参数
- 或新增 `run_replay_qwen.py` / BAT 入口
- 利用已有的 `build_stream_markdown.py` auto-route 能力

---

## 验证数据

```
视频: replay-verify-20260530 (vzuu.com)
时长: 160min | 帧数: 534 | 转写: 52,934 字
Qwen Plus + 128f + sliding-window: 7 窗口, overlap 226, 139,075 chars
```

overlap 修复验证通过（0 → 226）。以上缺口不影响直播流路径。

---

## 临时桥接脚本

`scripts/convert_payload_to_chunks.py` — 可用作标准转换的参考实现。
