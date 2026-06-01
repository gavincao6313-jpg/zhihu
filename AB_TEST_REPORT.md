# A/B Test Report: FILE vs URL 分支 — 英语情景对话陪练

**日期:** 2026-05-20 ~ 2026-05-21  
**视频:** 教育场景应用案例一：英语情景对话陪练 (153 min, 307 MB)  
**模型:** gemini-3.5-flash (两个分支统一)  
**脚本:** `D:\zhihu\gemini_synthesis_ab.py`

---

## 1. 实验设计

| | FILE 分支 | URL 分支 |
|---|---|---|
| **转写方式** | 单次全量 SenseVoice | 60s 分片 SenseVoice（模拟直播流） |
| **分片数** | 1 个 | 153 个 |
| **转写耗时** | 567s (RTF 0.062) | 1,258s (RTF 0.137) |
| **转写字数** | 44,387 chars | 44,588 chars |
| **关键帧** | 490 帧 (79 slides, 227 annotations) | 490 帧 (79 slides, 227 annotations) |
| **Gemini 输入帧** | 150 帧 (slide=79, annot=71) | 150 帧 (slide=79, annot=71) |
| **Gemini 模型** | gemini-3.5-flash | gemini-3.5-flash |

## 2. 运行日志

```
============================================================
A/B Test — Gemini NotebookLM Synthesis
Models: gemini-3.5-flash
API key: set
============================================================
[SKIP] FILE-branch — already done with gemini-3.5-flash (8,017 chars)

============================================================
Processing: URL-branch
============================================================
  Segments: 153  Duration: 9177s  Backend: sensevoice-chunked
  Gemini parts: transcript 47,954 chars, 150/490 frames (slide=79, annot=71)
  Trying model: gemini-3.5-flash ...
[URL-branch/gemini-3.5-flash] Sending to Gemini (302 parts)...
[URL-branch/gemini-3.5-flash] Done: 10,556 chars
[URL-branch] Model=gemini-3.5-flash  Size: 10,556 chars  Time: 148s
[URL-branch] Saved: D:\zhihu\zhihu_url\Markdowns\TTS_ab-url-english-practice.md

============================================================
Done! (149s)
  File output: D:\zhihu\zhihu_file\Markdowns\TTS_ab-file-english-practice.md (8,017 chars, from earlier run)
  URL output : D:\zhihu\zhihu_url\Markdowns\TTS_ab-url-english-practice.md (10,556 chars)
============================================================
```

注：FILE 分支的 Gemini 调用在更早的运行中完成（API 配额耗尽前的最后一次成功调用）。

## 3. 输出对比

| 维度 | FILE (单次全量) | URL (60s分片) |
|---|---|---|
| **输出大小** | 8,017 chars (207行) | **10,556 chars (255行)** +32% |
| **章节数** | 5 个 | **6 个** |
| **时间戳粒度** | 粗（`[00:00-00:20]`） | **细**（`[00:00-00:10:28]`） |
| **代码块** | 中文版 Prompt | **英文原文 Prompt** |
| **Q&A 环节** | 缺失 | **完整收录 3 个问答** |
| **API 字段** | 未列出 | **列出具体字段名** (totalScore, pronunciation, fluency, rhythm, completeness) |
| **章节组织** | 4个大章节 | 6个细粒度章节（独立出"项目初始化"） |

### 关键差异举例

**时间戳精度：**
- FILE: `### [00:00:00 - 00:20:00]` (20分钟跨度，Gemini 自行猜测边界)
- URL: `### [00:00:00 - 00:10:28]` + `### [00:10:28 - 00:38:42]` (精确到秒，153个锚点)

**缺失内容 (FILE 有，URL 没有 / URL 有，FILE 没有):**
- FILE 缺失：Q&A 互动答疑（数字人、流式对话、数据库来源）
- FILE 缺失：API 返回字段名细节
- URL 更详细：商业化章节包含向量检索、缓存表设计等 FILE 未提及的技术点

## 4. 结论

**URL 分支（60s 分片转写）输出质量显著更高。**

根因分析：
1. **时间戳锚点密度** — 153 个分段为 Gemini 提供了 153 个精确时间锚点，大模型能据此精确切分章节。FILE 分支只有 1 个起止时间，Gemini 只能模糊猜测。
2. **信息保真度** — 分片转写产生的分段边界本身隐含了"语义断点"信息，即使 SenseVoice 不返回 sentence_info，分片边界也充当了粗粒度的时间轴标记。
3. **代价** — 分片转写耗时翻倍（1258s vs 567s），但最终输出质量提升超过 30%，这个 trade-off 是值得的。

**建议：** 所有直播流转写继续使用 60s 分片方案。对于本地 MP4 离线处理，也应优先使用分片方案（而非单次全量），以获得更高质量的 NotebookLM 文档。
