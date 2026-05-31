# 本地 MP4 双模型验证 — MAC 端接手 Handoff

**日期**: 2026-05-31
**视频**: 实操带练：客服与标书工作流作业解析（3h, 256MB）
**目标**: 将 `build_stream_markdown.py` 中成熟的 Qwen 防压缩 QC 体系移植到本地 MP4 处理流水线

---

## 1. 当前产物

### 脚本
- **`d:\zhihu\zhihu_file\run_dual_model.py`** — 本次创建的本地 MP4 双模型验证入口（见附录完整源码）

### 输出文件（`d:\zhihu\zhihu_file\Markdowns\`）
| 文件 | 模型 | 字数 | 帧覆盖 |
|------|------|------|--------|
| `TTS_0531_实操带练：客服与标书工作流作业解析-gemini.md` | gemini-3.5-flash | 10,655 | 408/408 |
| `TTS_0531_实操带练：客服与标书工作流作业解析-qwen.md` | qwen3.6-plus (分窗) | 4,382 | 408/408 |
| `TTS_0531_实操带练：客服与标书工作流作业解析-manifest.json` | — | — | — |

### 预处理缓存（可直接复用）
```
d:\zhihu\zhihu_file\cache\transcripts\实操带练：客服与标书工作流作业解析.json  (152 KB)
d:\zhihu\zhihu_file\cache\keyframes\实操带练：客服与标书工作流作业解析\manifest.json
d:\zhihu\zhihu_file\cache\keyframes\实操带练：客服与标书工作流作业解析\frame_*.jpg (408 files)
```
- 188 分段, 50,582 字逐字稿
- 408 关键帧 (10 slide + 200 annotation + 198 context)
- Backend: SenseVoiceSmall + FSMN-VAD, CPU

---

## 2. 核心发现：QC 体系缺失

### 问题
Qwen 分窗合成 Assembly 后输出 4,382 字，body/transcript = **0.087**，远低于 `build_stream_markdown.py:74` 定义的阈值 `QWEN_BODY_MIN_TRANSCRIPT_RATIO = 0.20`。

### 根因
`run_dual_model.py` 的 Qwen 路径只做了：
1. 分窗 (Pass 1): 每窗口独立调用 Qwen → 窗口笔记
2. 拼合 (Pass 2): Qwen Assembly 将窗口笔记合并

但**缺失**了 `build_stream_markdown.py` 中的三层 QC：

### 缺失的 QC 机制（均在 `zhihu_url/scripts/build_stream_markdown.py`）

#### (a) 压缩比检测 + 自动重试
```python
# L74-76
QWEN_BODY_MIN_TRANSCRIPT_RATIO = 0.20   # body/transcript < 20% → overcompressed
QWEN_FACT_RETENTION_MIN_RATIO = 0.90   # 关键事实保留率
QWEN_NARRATIVE_RETENTION_MIN_RATIO = 0.32  # 叙事块保留率

# L1956-1961: 自动检测 + 重试
if len(gemini_text) / len(transcript) < QWEN_BODY_MIN_TRANSCRIPT_RATIO:
    print(f"[!] Qwen overcompressed, retrying...")
    _qw_quality_retries += 1
```

#### (b) 关键事实提取 + 附录追加
```python
# L830-880: extract_qwen_critical_facts()
# L1063-1090: ensure_qwen_critical_fact_appendix()
```
从窗口笔记中提取关键事实列表，如果最终输出中丢失则确定性追加 `## 关键事实附录`。

#### (c) 叙事证据附录追加
```python
# L916-982: extract_qwen_narrative_blocks()
# L1259-1302: ensure_qwen_narrative_appendix()
```
从窗口笔记中提取叙事块（时间戳锚点 + 论点 + 原话），如果拼合压缩则确定性追加 `## 6. 叙事证据附录`。

#### (d) 输出质量 QC 检测
```python
# L1476-1535: check_qwen_notebooklm_quality()
# L1541-1567: check_qwen_window_coverage()
# L1000-1035: check_qwen_fact_retention()
# L1099-1140: check_qwen_timeline_overlaps()
# L1202-1256: check_qwen_narrative_retention()
```

---

## 3. 建议的移植方案

### 最小可行方案（Phase 1）
在 `run_dual_model.py` 的 Assembly 之后加入：

```python
# After assembly, check compression ratio
body_chars = len(qwen_text)
transcript_chars = len(transcript_text)
body_ratio = body_chars / transcript_chars if transcript_chars > 0 else 0

if body_ratio < 0.20:
    # 确定性追加窗口笔记原文作为叙事证据附录
    appendix_lines = [
        "",
        "## 叙事证据附录",
        "",
        "> Assembly 拼合压缩比 {:.2f} < 0.20, 以下为窗口笔记原文, 用于防止细节丢失。".format(body_ratio),
        "",
    ]
    for i, note in enumerate(window_notes):
        appendix_lines.append(f"### 窗口 {i+1} 笔记原文")
        appendix_lines.append(note)
        appendix_lines.append("")
    qwen_text = qwen_text.rstrip() + "\n" + "\n".join(appendix_lines)
    # 重新保存
```

### 完整方案（Phase 2）
将 `build_stream_markdown.py` 中的以下函数提取到 `utils.py` 共享，然后 `run_dual_model.py` 调用：
- `extract_qwen_critical_facts()` — 从窗口笔记提取关键事实
- `extract_qwen_narrative_blocks()` — 提取叙事证据块
- `ensure_qwen_critical_fact_appendix()` — 追加关键事实附录
- `ensure_qwen_narrative_appendix()` — 追加叙事证据附录
- `check_qwen_notebooklm_quality()` — 输出质量检测
- `check_qwen_fact_retention()` — 事实保留检测

### 长期方案
将 `run_dual_model.py` 的分窗+Assembly 逻辑与 `build_stream_markdown.py` 的 sliding-window 合成完全对齐，共用同一套 window → fact/narrative extraction → final assembly pipeline。

---

## 4. 关键代码引用

| 机制 | 文件 | 行号 |
|------|------|------|
| 压缩比阈值 | `scripts/build_stream_markdown.py` | L74-76 |
| check overcompressed | `scripts/build_stream_markdown.py` | L1476-1535 |
| auto-retry on overcompress | `scripts/build_stream_markdown.py` | L1956-1961 |
| ensure narrative appendix | `scripts/build_stream_markdown.py` | L1259-1302 |
| ensure critical fact appendix | `scripts/build_stream_markdown.py` | L1063-1090 |
| extract critical facts | `scripts/build_stream_markdown.py` | L830-880 |
| extract narrative blocks | `scripts/build_stream_markdown.py` | L916-982 |
| call_qwen (reusable) | `utils.py` | L200-340 |
| call_gemini (reusable) | `utils.py` | L52-143 |

---

## 5. 其他踩坑记录

1. **Windows GBK 编码**: `sys.stdout.reconfigure(encoding="utf-8")` 必须在第一个 print 之前调用
2. **Gemini 2.5-pro 免费配额**: 818 parts (含 408 图) 时常触发 429，默认切到 `gemini-3.5-flash`
3. **Qwen DashScope 限制**: 每请求最多 250 data-uri 图片（error: `Exceeded limit on max data-uri per request: 250`）
4. **SenseVoice 模型重复加载**: `transcribe_audio_chunked` 每 chunk 都重新 `AutoModel(...)`，188 chunks ≈ 24 min。优化方向：提取 AudioModel 到外层单例
5. **视频文件路径**: `d:\zhihu\zhihu_file\Videos\实操带练：客服与标书工作流作业解析.mp4`

---

## 附录: run_dual_model.py 完整源码

见 `d:\zhihu\zhihu_file\run_dual_model.py`（373 行），核心流水线：

```
Phase 1: 预处理 (SenseVoice 关键帧 + 分片转录) → cache/
Phase 2: 构建输入 (PROMPT + transcript + 408 frames)
Phase 3: Gemini 合成 → gemini.md
Phase 4: Qwen 分窗合成
  ├─ Window 1 (204 frames) → Qwen → note1
  ├─ Window 2 (204 frames) → Qwen → note2
  └─ Assembly (note1 + note2) → Qwen → qwen.md
Phase 5: 生成 manifest.json
```
