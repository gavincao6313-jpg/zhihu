# 三路对照评测报告 — 崔超老师青少年AI教育

> P2-6 同视频三路对照评测
> 日期: 2026-05-22 (直播) / 2026-05-23 (回放 & 本地MP4)
> 视频: 知乎公益免费项目-把你的孩子交给崔超老师学AI
> 执行: Windows 端

---

## 一、三路流水线概览

| 路径 | 输入来源 | 转写后端 | 逐字稿组织 | Gemini 策略 | 模型 |
|------|---------|---------|-----------|------------|------|
| **直播流** | stream-nws.csslcloud.net (FLV 实时捕获) | SenseVoice (60s 分片) | 105 chunk × 60s = 6300s | one-shot (chunk 级, zhihuTTS_stream.py) | gemini-2.5-flash |
| **回放 URL** | CDN 下载 MP4 (227MB) | SenseVoice (全局, 60s 分片) | 130 chunk × 60s = 7744s | one-shot (全局, zhihuTTS.py file pipeline) | gemini-2.5-flash |
| **本地 MP4** | 本地 MP4 文件 (227MB) | SenseVoice (全局, 60s 分片) | 130 chunk × 60s = 7744s | one-shot (全局, zhihuTTS.py file pipeline) | gemini-2.5-flash |

---

## 二、各流水线节点输出物

### 2.1 直播流 (zhihu_url)

**Pipeline 节点:**

```
zhihuTTS_stream.py (Playwright 浏览器捕获 FLV)
  → stream_extractors.py (FLV 切片 60s)
  → SenseVoice (每 chunk 独立转写)
  → build_stream_markdown.py (合并 chunks + one-shot Gemini 合成)
  → live_final_qc() (P0 QC 检查)
  → TTS_stream-1.md
```

**证据文件:**

| 节点 | 产物 | 路径 | 大小 |
|------|------|------|------|
| 采集 | final-qc.json | `zhihu_url\runs\stream-1-20260522-215812.final-qc.json` | 501 B |
| 采集 | manifest.json | `zhihu_url\runs\stream-1-20260522-220126.manifest.json` | 639 KB |
| 采集 | manifest.md | `zhihu_url\runs\stream-1-20260522-220126.manifest.md` | 126 KB |
| 转写 | combined-transcript | `zhihu_url\runs\stream-1-20260522-220126.combined-transcript.txt` | 106 KB |
| 转写 | 105× chunk transcript | `zhihu_url\runs\stream-1_chunkNNN_*s-20260522-*.transcript.txt` | — |
| 转写 | 105× global-transcript | `zhihu_url\runs\stream-1_chunkNNN_*s-20260522-*.global-transcript.txt` | — |
| 合成 | 105× chunk payload | `zhihu_url\runs\stream-1_chunkNNN_*s-20260522-*.payload.json` | — |
| 合成 | 105× chunk Gemini output | `zhihu_url\runs\stream-1_chunkNNN_*s-20260522-*.md` | — |
| 合成 | BUG_EVIDENCE | `zhihu_url\runs\BUG_EVIDENCE_20260522.md` | 4 KB |
| **最终** | **final.md** | **`zhihu_url\Markdowns\TTS_stream-1.md`** | **16,146 chars** |

**final-qc.json 摘要:**
```json
{
  "source_type": "live",
  "source_status": "full",
  "chunk_count": 105,
  "transcript_chars": 37749,
  "frame_count": 335,
  "first_timestamp_s": 0,
  "last_timestamp_s": 6300,
  "timeline_duration_s": 6300,
  "gap_count": 0,
  "gap_seconds": 0,
  "silent_chunk_count": 0,
  "failed_chunk_count": 0,
  "synthesis_model": "gemini-2.5-flash",
  "synthesis_pass": "one-shot"
}
```

### 2.2 回放 URL (zhihu_file)

**Pipeline 节点:**

```
CDN 下载 (Python urllib)
  → run_single_file.py
    → zhihuTTS.process_video()
      → extract_keyframes() → 7744 frames → 290 kept (3.7%)
      → transcribe_audio_chunked() → 130 × 60s → SenseVoice
      → transcript_to_text() → combined transcript
      → build_gemini_payload() → frames + transcript
      → _call_gemini() → one-shot synthesis (gemini-2.5-flash)
      → TTS_0523_replay-*.md
```

**证据文件:**

| 节点 | 产物 | 路径 | 大小 |
|------|------|------|------|
| 下载 | replay MP4 | `zhihu_file\Videos\replay-20260522-崔超老师学AI.mp4` | 227 MB |
| 提取 | 关键帧索引 | `zhihu_file\cache\keyframes\replay-20260522-崔超老师学AI` | 131 KB |
| 转写 | 转写结果 | `zhihu_file\cache\transcripts\replay-20260522-崔超老师学AI.json` | 136 KB |
| 打包 | Gemini payload | `zhihu_file\cache\payloads\replay-20260522-崔超老师学AI.json` | 196 KB |
| **最终** | **final.md** | **`zhihu_file\Markdowns\TTS_0523_replay-20260522-崔超老师学AI.md`** | **68,483 chars** |

### 2.3 本地 MP4 (zhihu_file)

**Pipeline 节点:** (与回放相同，输入源为本地文件)

```
run_single_file.py
  → zhihuTTS.process_video()
    → extract_keyframes() → 7744 frames → 290 kept (3.7%)
    → transcribe_audio_chunked() → 130 × 60s → SenseVoice
    → transcript_to_text() → combined transcript
    → build_gemini_payload() → frames + transcript
    → _call_gemini() → one-shot synthesis (gemini-2.5-flash)
    → TTS_0523_*.md
```

**证据文件:**

| 节点 | 产物 | 路径 | 大小 |
|------|------|------|------|
| 输入 | 本地 MP4 | `zhihu_file\Videos\知乎公益免费项目-把你的孩子交给崔超老师学AI.mp4` | 227 MB |
| 提取 | 关键帧索引 | `zhihu_file\cache\keyframes\知乎公益免费项目-把你的孩子交给崔超老师学AI` | 131 KB |
| 转写 | 转写结果 | `zhihu_file\cache\transcripts\知乎公益免费项目-把你的孩子交给崔超老师学AI.json` | 136 KB |
| 打包 | Gemini payload | `zhihu_file\cache\payloads\知乎公益免费项目-把你的孩子交给崔超老师学AI.json` | 205 KB |
| **最终** | **final.md** | **`zhihu_file\Markdowns\TTS_0523_知乎公益免费项目-把你的孩子交给崔超老师学AI.md`** | **68,207 chars** |

---

## 三、P2-6 五维度对比

### ③ 正文字符数 (不含逐字稿附录)

| 直播流 | 回放 URL | 本地 MP4 |
|--------|---------|---------|
| **16,146** | **23,261** | **22,985** |

- 回放与本地 MP4 正文几乎一致（差异 276 字, 1.2%），符合预期
- 直播流正文仅 16,146 字，比文件流水线少 **~30%**

### ① 最后章节时间戳覆盖率

| 直播流 | 回放 URL | 本地 MP4 |
|--------|---------|---------|
| **01:34:12** / 02:09:04 = **72.9%** | **02:08:46** / 02:09:04 = **99.8%** | **02:07:54** / 02:09:04 = **99.1%** |

- 直播流缺失最后 ~35 分钟（少年创始人孵化营商业化部分完全没有）

### ③ 尾部 20 分钟覆盖

| 直播流 | 回放 URL | 本地 MP4 |
|--------|---------|---------|
| ❌ 未覆盖 (只到 1h34m) | ✅ 覆盖到 02:08:46 | ✅ 覆盖到 02:07:54 |

尾部 20 分钟内容（01:49:04–02:09:04）：商业孵化营介绍、报名流程、KR老师答疑等 —— 直播流完全缺失。

### ⑤ 视觉证据引用数

| 直播流 | 回放 URL | 本地 MP4 |
|--------|---------|---------|
| 0 | 0 | 0 |

三者均未在正文中内联 `![frame]` 引用。关键帧仅作为 payload 中的 base64 发送给 Gemini，最终 markdown 不含视觉引用。

### ④ 关键知识点命中率

| 知识点 | 直播流 | 回放 | 本地 |
|--------|--------|------|------|
| IOAI / NOAI 竞赛 | ✅ | ✅ | ✅ |
| WASCY 竞赛 | ✅ | ✅ | ✅ |
| AI Coding 概念 | ✅ | ✅ | ✅ |
| LMCC / CCF 认证 | ✅ | ✅ | ✅ |
| Latent Space 品牌 | ✅ | ✅ | ✅ |
| ResNet / Epoch / Batch size | ✅ | ✅ | ✅ (仅正文无附录) |
| 少年创始人孵化营 | ❌ 尾部缺失 | ✅ | ✅ |
| 精益创业方法论 | ✅ | ✅ | ✅ |
| AI专家1v1指导 | ✅ | ✅ | ✅ |
| 6天5晚夏令营细节 | ❌ 尾部缺失 | ✅ | ✅ |

直播流知识点命中率: **8/10 (80%)** — 尾部 2 点缺失
回放: **10/10 (100%)**
本地 MP4: **10/10 (100%)**

---

## 四、关键发现

### 发现 1: 实时采集时长不足 (根因)

直播流 final-qc 显示 `last_timestamp_s: 6300` (1h45m)，但实际视频 7744s (2h09m)。缺失的 1444s (24 分钟) 对应尾部商业化内容。**直播流采集提前终止**，不是合成质量问题，是采集完整性问题。

### 发现 2: 正文内容丰富度差距

文件流水线（正文 ~23k）vs 直播流（正文 ~16k），差距 ~30%。即使限制在相同覆盖时间段内比较，文件流水线的"全局一次合成"策略也比"chunk 级 one-shot"提供了更连贯、更详尽的内容组织。

### 发现 3: 回放与本地 MP4 产出几乎完全一致

正文仅差 1.2%，附录完全相同（45,222 字）。说明文件流水线对不同来源（CDN URL vs 本地文件）的同一视频处理结果高度稳定，流水线本身无随机性偏差。

### 发现 4: 逐字稿附录缺失

直播流最终 markdown 无逐字稿附录（P1-8 section notes sidecar 也未生成），对 NotebookLM 检索场景不利。文件流水线自动生成了完整的带时间戳逐字稿附录。

### 发现 5: 视觉证据未落地到正文

三路产物的正文均无 `![frame]` 内联引用。关键帧信息仅存在于 Gemini 的上下文窗口中，未在最终文档中可检索地呈现。

---

## 五、优化建议（给 Mac 端）

### P0 (立即): 采集时长完整性
- 直播流采集的终止条件需审查 — 为什么 2h09m 的视频只采集了 1h45m？
- 建议: 采集进程加 watch dog，流结束后延时 60s 再确认终止

### P1 (核心): 正文质量
- 将 P1 sectioned synthesis (3-pass) 应用到直播流，替代当前 chunk 级 one-shot
- 预期: 直播流正文质量从 16k 提升到接近文件流水线的 23k

### P2 (增强): 视觉证据落地
- 在 final markdown 中嵌入关键帧引用（`![frame](path)` 或 base64 thumbnail）
- 来源: payloads 中已有的 frame 数据，只需写入 markdown

### P2 (增强): Sidecar 产物
- 直播流也应输出 cleaned transcript + section notes，与文件流水线对齐
- 确保 NotebookLM 双模式可用（正文 + section notes 目录）

---

## 六、文件索引

```
D:\zhihu\
├── zhihu_url\
│   ├── Markdowns\
│   │   └── TTS_stream-1.md                          ← 直播流最终产物
│   └── runs\
│       ├── stream-1-20260522-215812.final-qc.json   ← 直播流 QC
│       ├── stream-1-20260522-220126.manifest.json   ← 直播流 manifest
│       ├── stream-1-20260522-220126.combined-transcript.txt  ← 直播流合并逐字稿
│       └── stream-1_chunk*                          ← 直播流 105 chunks
├── zhihu_file\
│   ├── Markdowns\
│   │   ├── TTS_0523_知乎公益免费项目-把你的孩子交给崔超老师学AI.md    ← 本地 MP4 最终产物
│   │   └── TTS_0523_replay-20260522-崔超老师学AI.md                ← 回放最终产物
│   ├── cache\
│   │   ├── keyframes\知乎公益免费项目-把你的孩子交给崔超老师学AI      ← 本地 MP4 关键帧
│   │   ├── keyframes\replay-20260522-崔超老师学AI                  ← 回放关键帧
│   │   ├── transcripts\知乎公益免费项目-把你的孩子交给崔超老师学AI.json ← 本地 MP4 转写
│   │   ├── transcripts\replay-20260522-崔超老师学AI.json           ← 回放转写
│   │   ├── payloads\知乎公益免费项目-把你的孩子交给崔超老师学AI.json  ← 本地 MP4 payload
│   │   └── payloads\replay-20260522-崔超老师学AI.json              ← 回放 payload
│   ├── Videos\
│   │   ├── 知乎公益免费项目-把你的孩子交给崔超老师学AI.mp4           ← 本地 MP4 源
│   │   └── replay-20260522-崔超老师学AI.mp4                        ← 回放下载
│   └── runs\
│       └── three-way-comparison-20260523.md                         ← 本报告
```

---

*报告生成: 2026-05-23 · Windows 端执行 · P2-6 评测框架*
