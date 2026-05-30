# 直播流转写 BUG 报告 — 2026-05-29

## 直播信息

- **URL**: `https://www.zhihu.com/xen/training/live/room/2043385286353277432/2043386327295685045`
- **主题**: RAG已死？是炒作吗？我们认真测了 LLM Wiki
- **时长**: ~2小时31分钟
- **分片**: 151 chunks
- **转写**: 54,204 字 | 696 帧 | 64 次幻灯片切换

---

## BUG #1: Playwright greenlet 崩溃导致 pipeline 中断

### 现象
直播结束后，ffmpeg 正确检测到 HLS 404，但 Playwright 在退出时抛出异常：
```
greenlet.error: cannot switch to a different thread (which happens to have exited)
```
导致 BAT worker 无法读取 `stream-base-*.txt` marker 文件，后续步骤 2-4（合并、NotebookLM、幻灯片）全部未自动执行。

### 影响
- Worker 卡在 `Press any key to continue` 交互提示
- 需手动运行 merge → build_markdown → extract_slides
- 转写本身（步骤 1）未受影响，151 chunks 完整

### 复现
- 环境: Windows 10, Python 3.12, playwright (sync API)
- 文件: `zhihuTTS_stream.py` — PlaywrightKeepaliveStream
- 触发条件: 流结束后 Playwright 的 `SyncBase._sync` greenlet 切换失败

### 建议修复
- Playwright sync API 在 Windows 上的线程/greenlet 退出时序问题
- 可能需要在 stream end 时显式关闭 Playwright context，避免隐式析构
- 或改为 try/except 包裹 base marker 读取，降级为从日志推断 BASE_STEM

---

## BUG #2: Qwen 模型输出非确定性严重

### 现象
同一输入（128 帧 + 54K 字转写），同参数（qwen3.6-flash, 128 frames, one-shot），三次运行结果天差地别：

| 次序 | 章节数 | 覆盖 | 生成字符 | 裁定 |
|------|--------|------|----------|------|
| 第1次 | 10 | 00:00–02:31 (完整, gap 48s) | 11,113 | ✅ 最佳 |
| 第2次 | 1 | 00:00–00:04 (崩溃) | — | ❌ overcompressed_body |
| 第3次 | 8 | 00:00–02:30 (完整) | ~11,000 | ⚠️ 可用 |

第2次运行时 QC 标记 `qwen_overcompressed_body: body/transcript ratio 0.19`，模型把 token 预算花在 Glossary（8 词条）和元数据上，正文仅产出 1 个章节。

### 影响
- 笔记质量完全不可预测
- 无法作为可靠的自动化 pipeline 环节
- Cron 自动补跑逻辑在此情况下无意义（跑出来可能是废的）

### 建议
- 考虑加入 retry + QC 门禁：body_coverage gap > 120s 或 overcompressed_body → 自动重跑
- 或在 prompt 中明确限制 Glossary 长度，优先保证正文覆盖

---

## BUG #3: Qwen 全系输出长度天花板

### 现象
所有 Qwen 变体在本次 2.5 小时直播任务上，生成字符均在 10K-11K 范围：

| 模型 | 帧数 | 生成字符 | 覆盖 |
|------|------|----------|------|
| qwen3.6-flash | 128 | 11,113 | 完整（仅1次） |
| qwen3.6-flash | 250 | 10,837 | 截断 81 分钟 |
| qwen3.6-plus | 128 | 10,642 | 截断 41 分钟 |

而 Gemini 3.5 Flash 全量 696 帧生成了 15,522 字符，完整覆盖。

### 分析
- Qwen 在 multimodal（文字+图片）输入场景下，似乎有隐式的输出长度限制
- 帧数增加（128→250）反而压缩了正文输出（更多图片 token 挤占输出预算）
- qwen3.6-plus 没有比 flash 更好——plus 的 "更强推理" 在这个结构化长文任务上未体现优势

### 建议
- 直播笔记场景以 Gemini 为主力模型
- Qwen 作为低成本备选，但需接受非确定性
- 或尝试将任务拆分为多段（每 30 分钟一段），逐段合成后拼接

---

## BUG #4: URL 中 `=` 被 cmd.exe 参数解析截断

### 现象
直播间 URL 包含 `?is_hybrid=1`，在 BAT 脚本中 `=1` 被 cmd.exe 解析为独立参数，导致：
- URL 变为 `?is_hybrid`（丢失 `=1`）
- `1` 被误设为输出名称

### 修复
使用 URL 编码 `%3D` 替代 `=`：`?is_hybrid%3D1`

### 建议
- BAT 脚本增加 URL 合法性校验（检测 `?` 后是否有 `=`）
- 或自动替换 `=` 为 `%3D`

---

## 模型对比速查表

| 模型 | 帧数 | 稳定性 | 覆盖 | 推荐 |
|------|------|--------|------|:--:|
| Gemini 3.5 Flash | 696 | ⭐⭐⭐ 稳定 | 完整 | ✅ 主力 |
| Qwen3.6-flash | 128 | ⭐ 非确定 | 看运气 | ⚠️ 备选 |
| Qwen3.6-plus | 128 | ⭐ 非确定 | 不稳定 | ❌ 不推荐 |
| Qwen3.6-flash | 250 | ⭐ 非确定 | 必截断 | ❌ 不推荐 |

---

## 输出文件

### 保留的笔记
- `Markdowns/TTS_stream-...-gemini35.md` (270 KB) — Gemini 主力
- `Markdowns/TTS_stream-...-qwen-128.md` (259 KB) — Qwen flash 128帧
- `Markdowns/TTS_stream-...-qwen-plus.md` (260 KB) — Qwen plus 128帧（截断）

### 完整转写
- `runs/stream-...-combined-transcript.txt` (145 KB)
- `runs/stream-...-merged.md` (147 KB)
- `runs/stream-...-manifest.md` + `.json`

### 幻灯片
- `Slides/.../slides.pdf` + `slides.pptx`
