# 2026-06-01 知乎直播转写 Handoff

> **From**: Windows Run Owner → **To**: Mac Code Owner
> **直播**: 医疗行业AI转型一应用 | **时长**: 2h46min | **日期**: 2026-06-01

---

## 一、启动阶段问题（严重程度：高）

### 1.1 灾难级启动（4 次尝试才成功）

| 尝试 | 方式 | 结果 | 根因 |
|:--:|------|------|------|
| 1 | `.\run_zhihu_live.bat "URL"` 在 PowerShell | 名称变 "1"，参数解析错 | PowerShell 对 .bat 的引号处理导致 URL 被拆分 |
| 2 | `Start-Process -ArgumentList` 数组 | 进程启动后秒退 | PS 5.1 的 `-ArgumentList` 引号转义不可靠 |
| 3 | `cmd /c "bat URL"` 包在背景任务 | 背景任务被杀时进程树全死 | PowerShell 背景任务停掉时杀整个进程树 |
| 4 | `Start-Process -WindowStyle Hidden` + 独立 cmd | **成功** ✅ | 完全独立进程，需外层双引号包裹 |

**唯一正确启动命令**（已验证）:
```powershell
$url = '<URL>'
$workDir = 'd:\zhihu\zhihu_url'
$cmdArgs = '/c ""d:\zhihu\zhihu_url\run_zhihu_live.bat" "' + $url + '" --no-gemini"'
Start-Process -FilePath "cmd.exe" -ArgumentList $cmdArgs -WindowStyle Hidden -WorkingDirectory $workDir
```

### 1.2 由此产生的 SOP

已编写完整 SOP: **`d:\zhihu\zhihu_file\docs\LIVE_STREAM_SOP.md`**

覆盖：前置检查 → 启动 → 验证 → 故障处理 → 直播后操作。每次直播必须遵循。

---

## 二、流结束检测 BUG（严重程度：严重）🔴

### 2.1 现象

同一天**复现 2 次**，100% 触发率。

直播结束后，流水线不在"老师已退出"阶段正常停止，而是崩溃：
```
ffmpeg exited (code=0)
→ Recorder 检查 is_stream_ended() → 未检测到结束信号
→ Recorder 进入 refresh_and_get() → Playwright page.reload()
→ greenlet.error: cannot switch to a different thread
→ Python 进程崩溃
→ bat worker 读不到 base marker → 后续步骤 [2/4][3/4][4/4] 全部跳过
```

### 2.2 根因分析

位置: `stream_extractors.py`:

1. **`is_stream_ended()` (line ~496)** 依赖 DOM 中检测 `"等待老师进入教室"` 文本，但知乎 CC 直播结束后可能显示不同内容，导致检测失败
2. 检测失败后进入 `refresh_and_get()` (line ~417)，页面 reload 触发 greenlet 崩溃
3. `latest_stream()` 中的异常处理没有捕获 greenlet 错误

### 2.3 建议修复方向

```
方案A: 增强 is_stream_ended() 对知乎 CC 的检测
  - 增加更多结束信号关键词（如 "直播已结束"、"回放"、"观看回放"）
  - 多次检测确认（连续 N 秒 DOM 包含结束信号）

方案B: 在 refresh_and_get() 中增加 greenlet 保护
  - try/except greenlet.error
  - 捕获后直接 raise StreamEndedError

方案C: 增加 ffmpeg 自然退出时的超时等待
  - ffmpeg exit code=0 后等待 N 秒，检查 DOM 多次
  - 超时则视为 stream ended，不进入 refresh 路径
```

### 2.4 临时 Workaround

直播结束后手动执行 merge + synthesis（数据已全部保存）:
```powershell
python scripts\merge_stream_chunks.py --base "<BASE_STEM>" --runs-dir "runs"
python scripts\build_stream_markdown.py --base "<BASE_STEM>" --provider gemini ...
python scripts\build_stream_markdown.py --base "<BASE_STEM>" --provider qwen --qwen-max-frames 250 ...
```

---

## 三、Qwen 滑动窗口配置问题（严重程度：中）

### 3.1 问题

`--max-frames 128` "公平对比"参数反而对 Qwen 不公平：
- Gemini: 一次看到全部 436 帧
- Qwen: 被压到 128 帧/窗 → 5 个窗口 → 4 个重叠区(66 分钟)

### 3.2 解决方案

Qwen 应使用全能力 250 帧/窗（硬上限）:
- 128 帧/窗: 5 窗口, 4 重叠, API 6 次 → **废弃**
- 250 帧/窗: 3 窗口, 0 重叠, API 4 次 → **推荐**

### 3.3 对 build_stream_markdown.py 的建议

`--fair-ab` / `--max-frames` 应该在两个 provider 上都生效。目前 Gemini one-shot 忽略 `--max-frames`。

---

## 四、双模型对比结论

### 输出文件

| 文件 | 大小 | 说明 |
|------|------|------|
| `Markdowns/TTS_stream-live_20260601_...-gemini35.md` | 217KB | Gemini one-shot |
| `Markdowns/TTS_stream-live_20260601_...-qwen-full.md` | 237KB | Qwen sliding-window 250帧 |

### 对比摘要

```
维度              Gemini    Qwen 250
─────────────────────────────────────
结构清晰度        ★★★★★    ★★★★
知识字典深度      ★★★      ★★★★★
技术细节          ★★★★★    ★★★★☆
叙事引用质量      ★★★      ★★★★★
完整性(无丢失)    ★★★★★    ★★★☆     (Qwen 丢失 1 个 narrative block)
可读性/教学价值   ★★★★     ★★★★★
API效率           ★★★★★    ★★★       (1 call vs 4 calls)
伦理/社会洞察     ★★★      ★★★★★
```

- **Gemini** 适合技术参考/工作流复现
- **Qwen** 适合教学材料/知识传播
- **互补关系**，非替代关系

---

## 五、完整输出物清单

### SOP 文档
- `d:\zhihu\zhihu_file\docs\LIVE_STREAM_SOP.md`

### 转录产物 (runs/)
```
stream-live_20260601_医疗行业AI转型一应用-merged.md                  # 结构化合并文档
stream-live_20260601_医疗行业AI转型一应用-20260601-225014.manifest.md  # 逐块统计 (177KB)
stream-live_20260601_医疗行业AI转型一应用-20260601-225014.combined-transcript.txt  # 完整逐字稿 (140KB)
stream-live_20260601_医疗行业AI转型一应用_chunk001~166_*.md           # 170 个分块
```

### QC 产物 (runs/)
```
stream-live_20260601_...-20260601-225004.gemini35.final-qc.json
stream-live_20260601_...-20260601-225004.qwen-full.final-qc.json  (Qwen 128 的 QC 已删除)
```

### NotebookLM 输出 (Markdowns/)
```
TTS_stream-live_20260601_医疗行业AI转型一应用-gemini35.md    (217KB, 推荐技术参考)
TTS_stream-live_20260601_医疗行业AI转型一应用-qwen-full.md   (237KB, 推荐教学材料)
```

### 日志 (logs/)
```
run-live-20260601-195537.log  # 第一轮 (19:55-20:00, Playwright 崩溃)
run-live-20260601-200148.log  # 第二轮 (20:01-22:50, 完整录制 + greenlet 崩溃)
```

### 本 Handoff
- `docs/handoff-20260601-live.md`

---

## 六、Mac 端建议行动项

| 优先级 | 行动 | 说明 |
|:--:|------|------|
| 🔴 P0 | 修复流结束检测 greenlet 崩溃 | 见第二节，100% 复现 |
| 🟡 P1 | 审查 `--max-frames` 对 one-shot 的影响 | Gemini one-shot 是否应支持 max_frames？ |
| 🟡 P1 | 增强 `is_stream_ended()` DOM 检测 | 增加知乎 CC 结束页面的关键词 |
| 🟢 P2 | 修复 `--fair-ab` 对称性 | 确保双模型都在相同限制下运行 |
| 🟢 P2 | 增加 `refresh_and_get()` greenlet 异常保护 | 防御性修复 |

---

> 🤖 Generated with [Claude Code](https://claude.com/claude-code)
> Windows Run Owner | 2026-06-01
