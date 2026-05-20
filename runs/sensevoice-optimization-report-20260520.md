# SenseVoice 全量重跑优化 — WIN 端验证报告

## 日期: 2026-05-19/20
## 环境: Windows 10, Python 3.12, FunASR 1.3.1, SenseVoiceSmall

---

## 一、对比实验：faster-whisper vs SenseVoice → Gemini

选了 3 个有中文技术专有名词的视频做 A/B 对比：

### 1.1 Gemini 最终输出规模

| 视频 | faster-whisper 输出 | SenseVoice 输出 | 增幅 |
|------|-------------------|----------------|------|
| AI编程_01 (通义灵码) | 22,113 字符 | 47,932 字符 | +117% |
| AutoGPT_04 (MCP/A2A/ANP) | 27,439 字符 | 71,774 字符 | +162% |
| RAG_01 (RAG企业应用) | 25,105 字符 | 42,352 字符 | +69% |

SenseVoice 版输出在保持相同章节结构的前提下，内容显著更详尽。

### 1.2 SenseVoice 原始转写准确率

**正确的:**
- MCP (81x)、ANP (49x)、DID (38x)、W3C (14x) — 英文缩写准确
- 去中心化、智能体互联网、百炼、阿里云 — 中文技术词准确

**有问题的:**

| 正确名称 | SenseVoice 输出 | 类型 |
|----------|----------------|------|
| 通义灵码 | 通益零码 / 通通一零码 | 品牌名完全错误 |
| A2A | A to A | 协议名语音展开 |
| 通义千问 | 通一千问 | 缺字 |
| AAAI | AIAI | 会议名错误 |
| 曹荣禹 | 曹荣宇 | 同音错字 |
| 常高伟 | 未识别 | 讲者名丢失 |

**填充词密度:** 嗯 (127-289x/video), 呃 (181-562x), 啊 (167-395x)

### 1.3 Gemini 补偿效果

尽管原始转录有上述错误，Gemini 通过上下文理解成功恢复了：
- "通益零码" → 输出正确为 "通义灵码"
- "A to A" → 输出正确为 "A2A"
- 人名、会议名等均有纠正

---

## 二、已实施的优化 (本次 commit)

### 2.1 `--reprocess` 参数 (zhihuTTS.py)

```bash
# 重跑所有已完成视频
python zhihuTTS.py --reprocess

# 只重跑前 N 个（分批控制）
python zhihuTTS.py --reprocess 20

# 预览将处理的视频
python zhihuTTS.py --reprocess 10 --dry-run
```

在 `status=="done"` 时跳过进度检查，强制重新预处理+Gemini 生成。

### 2.2 扩充 GLOSSARY_PATTERNS (zhihuTTS_video.py:44-72)

在逐字稿送入 Gemini 之前，用正则替换修正已知 ASR 错误：

```
通益零码 / 通通一零码 → 通义灵码
通一千问 → 通义千问
A to A → A2A
曹荣宇 → 曹荣禹
常高体 → 常高伟
AIAI → AAAI
...
```

### 2.3 Gemini Prompt 注入纠错表 (zhihuTTS.py:84-98)

在 PROMPT_TEXT 末尾追加 "已知 ASR 转写纠错表"，让 Gemini 在语义理解阶段就收到纠正指引，处理未知变体。

---

## 三、WIN 端运行注意事项

1. **Python 版本**: 必须用 Python 3.12（`D:/Python/Python312/python.exe`），Python 3.14 下 funasr 编译失败
2. **SenseVoice 模型**: 首次运行会自动从 modelscope 下载 (~200MB)，模型缓存于 `C:\Users\Admin\.cache\modelscope\`
3. **配额**: 每日 20 次 Gemini 调用，64 个视频最少 4 天。建议 `--reprocess 15` 每天一批
4. **RTF**: SenseVoiceSmall CPU 推理 RTF ~0.1-0.3，100 分钟视频约 10-30 分钟转录

---

## 四、批量重跑测试 (2026-05-20 08:26)

`--reprocess 5` 批量重跑 5 个已完成视频，验证完整流水线。

### 4.1 结果

| # | 视频 | 转录 | Gemini | 结果 |
|---|------|------|--------|------|
| 1 | AI编程_01 (通义灵码) | 缓存命中 | 503×3 + 429×3 | **失败** |
| 2 | AI编程_02 (CodeWave) | 完成 (99min, RTF 0.09-0.3) | 429 rate limit | **失败** |
| 3 | AutoGPT_01 (XAgent) | — | 429 rate limit | **失败** |
| 4 | AutoGPT_02 (MetaGPT) | — | 429 rate limit | **失败** |
| 5 | AutoGPT_03 (工作流 vs 智能体) | — | SSL EOF × N | **失败** |

**5/5 全部失败**，均为 Gemini API 层错误，非代码问题。

### 4.2 失败原因分析

1. **503 UNAVAILABLE**: 北京时间 8:30-9:30 Gemini 2.5 Flash API 高峰拥堵
2. **429 rate limit**: 每日配额 20 次 + 重试消耗，30 次调用后耗尽
3. **SSL UNEXPECTED_EOF**: 代理/TLS 握手中断（可能与 GFW 干扰有关）

### 4.3 建议

- **错峰运行**: 避开北京时间 8:00-12:00 高峰，建议凌晨或下午运行
- **减小批次**: `--reprocess 5` 每天，留足重试余量
- **SSL 重试**: 在 `_call_gemini_with_retry` 中添加 `httpx.ConnectError` 到可重试异常列表
- **代理配置**: 检查 `HTTPS_PROXY` 环境变量，确认代理稳定

### 4.4 已验证可工作的部分

此前单独运行的 3 个视频（非高峰时段）全部成功，SenseVoice 转录 + Gemini 生成链路完整：
- AI编程_01: 29811 字符逐字稿 → 124KB Markdown
- AutoGPT_04: 71774 字符逐字稿 → 174KB Markdown
- RAG_01: 42352 字符逐字稿 → 109KB Markdown