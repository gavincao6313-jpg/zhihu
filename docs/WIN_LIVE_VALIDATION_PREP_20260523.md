# WIN 直播流验证准备清单 - 2026-05-23

> 适用分支：`origin/main`
> 当前已确认基线：`ddf487b verify(win): MAC bug-071 idempotency fixes confirmed on Windows`
> 目标：今晚真实直播全程验证 `run_zhihu_live.bat` 默认 continuous HLS 路径、最终 Markdown QC、逐字稿/视觉证据附录、幻灯片提取。

---

## 1. 先拉取代码

```bat
cd /d D:\zhihu\zhihu
git pull origin main
git log --oneline -3
```

期望能看到最新提交包含本准备文档，并且历史里包含：

```text
ddf487b verify(win): MAC bug-071 idempotency fixes confirmed on Windows
21ec8b2 fix(slides): select stream payloads by manifest
cf3484a fix(live): default to continuous HLS and append audit evidence
```

不要切到 `feature/stream-transcript-validation` 跑今晚直播验证；今晚验证以 `main` 为准。

---

## 2. 运行前检查

### 2.1 登录态

若登录态过期，先扫码刷新：

```bat
python login_save_auth.py
```

### 2.2 工具与环境

BAT 会自动检查：

- `zhihu_auth_state.json`
- Cookie 有效性
- `ffmpeg`
- `ffprobe`
- `Videos\.stream` 可写性
- 磁盘空间
- `TRANSCRIBE_BACKEND`

建议直播前确认磁盘至少 10GB 以上。

### 2.3 Gemini API 选择

如果今晚只验证录制和转写质量，避免消耗 API：

```bat
run_zhihu_live.bat "<直播间URL>" --no-gemini
```

如果今晚要同时验证最终 NotebookLM 文档质量，不加 `--no-gemini`。这时只有最终 synthesis 会调用 Gemini：

- 采集/转写阶段：不调用 Gemini
- 最终文档阶段：`1 initial + 最多 2 continuation`
- retry cap：`2`

不要手动运行 `zhihuTTS_stream.py --gemini`。
不要使用 `run_zhihu_live.sh`。
不要启用 `scripts/live_sectioned_synthesis.py`。

---

## 3. Dry Run 必跑

正式直播前先 dry-run：

```bat
run_zhihu_live.bat "<直播间URL>" --dry-run
```

必须确认输出包含：

```text
采集模式            : continuous HLS recorder + async consumer
直播转写 Gemini       : disabled
Step 1: zhihuTTS_stream.py --continuous-hls --base-marker <marker> (no --gemini)
Step 2: merge_stream_chunks.py --base <resolved marker base>
Step 3: build_stream_markdown.py --base <resolved marker base> --max-retries 2 --max-continuations 2
Step 4: extract_slides.py --stream-base <resolved marker base> (PDF + PPTX)
```

若 dry-run 出现 `zhihuTTS_stream.py --gemini`，停止，不要正式跑。

---

## 4. 正式运行

推荐先用自动命名，避免同 base 多次运行混在一起：

```bat
run_zhihu_live.bat "<直播间URL>"
```

如果要完全避免 Gemini 消耗：

```bat
run_zhihu_live.bat "<直播间URL>" --no-gemini
```

不要传 `--resume`。当前 BAT 对 continuous HLS 默认入口会拒绝 `--resume`。

运行后窗口可以关闭，后台仍继续。重新查看日志：

```powershell
Get-Content -Wait -Tail 100 "logs\run-<日志名>.log"
```

---

## 5. 直播过程中重点观察

日志里应看到：

- `[1/4] 开始直播转写（continuous HLS，不在采集阶段调用 Gemini）`
- 实际输出名称：`live_YYYYMMDD_<页面标题>` 或指定名称
- HLS work dir 路径
- chunk 持续增长
- 无 `Traceback`
- 无连续 ffmpeg/ffprobe 错误
- 无 stream-stage Gemini 调用

如果中途意外中断，但 `Videos\.stream\<本次 HLS work dir>` 里已有 `.ts`，不要用 BAT `--resume`。改用：

```bat
python zhihuTTS_stream.py --hls-consumer-only --stream-work-dir "<上次日志中的 HLS work dir>"
```

---

## 6. 结束后检查产物

设实际输出名为 `<BASE>`。检查：

```bat
dir runs\stream-<BASE>-*.manifest.json
dir runs\stream-<BASE>-*.manifest.md
dir runs\stream-<BASE>-*.combined-transcript.txt
dir runs\stream-<BASE>-merged.md
dir Markdowns\TTS_stream-<BASE>.md
dir Slides\<BASE>\slides.pdf
dir Slides\<BASE>\slides.pptx
```

如果用了 `--no-gemini`，`Markdowns\TTS_stream-<BASE>.md` 可能不会生成，这是预期。

最终 Markdown 应包含：

- `Live Final QC`
- `附录 A：完整逐字稿`
- `附录 B：视觉证据索引`

可用：

```bat
findstr /C:"Live Final QC" "Markdowns\TTS_stream-<BASE>.md"
findstr /C:"附录 A：完整逐字稿" "Markdowns\TTS_stream-<BASE>.md"
findstr /C:"附录 B：视觉证据索引" "Markdowns\TTS_stream-<BASE>.md"
```

---

## 7. 必填验证记录

请新建一份验证报告，例如：

```text
runs/windows-live-validation-20260523.md
```

建议包含：

```markdown
# Windows Live Validation - 2026-05-23

## Git
- branch:
- commit:

## Command
- dry-run command:
- run command:
- with Gemini: yes/no

## Timeline
- start time:
- end time:
- total wall time:

## Outputs
- BASE:
- log file:
- manifest json:
- manifest md:
- combined transcript:
- merged md:
- final Markdown:
- slides PDF:
- slides PPTX:

## Key Metrics
- chunks:
- duration_s:
- transcript chars:
- frames:
- gaps:
- failed chunks:
- source_status:
- body_coverage_status:
- body_tail_gap_s:
- Gemini successful calls:

## Observations
- continuous HLS 是否全程工作:
- 是否出现录制缺口:
- 是否出现 Traceback:
- 是否出现 stream-stage Gemini:
- slide 提取是否成功:
- 最终 Markdown 尾部是否覆盖:

## Problems
- 问题:
- 日志片段:
- 临时处理:
```

---

## 8. 提交给 MAC 分析

优先提交这些文件：

- `runs/windows-live-validation-20260523.md`
- 本次 `runs/stream-<BASE>-*.manifest.json`
- 本次 `runs/stream-<BASE>-*.manifest.md`
- 本次 `runs/stream-<BASE>-*.final-qc.json`
- 本次 `runs/stream-<BASE>-merged.md`
- `Markdowns/TTS_stream-<BASE>.md`（如果生成）

不要提交：

- `logs/*.log`
- `Videos/.stream/**`
- 大体积 `.ts` / `.mp4`
- `zhihu_auth_state.json`
- `.env` / API key

提交示例：

```bat
git status
git add runs/windows-live-validation-20260523.md
git add runs/stream-<BASE>-*.manifest.json
git add runs/stream-<BASE>-*.manifest.md
git add runs/stream-<BASE>-*.final-qc.json
git add runs/stream-<BASE>-merged.md
git add Markdowns/TTS_stream-<BASE>.md
git commit -m "verify(win): live continuous HLS validation 20260523"
git push origin main
```

如果最终 Markdown 没生成（例如使用 `--no-gemini`），不要强行补跑；先提交录制/转写验证产物。

---

## 9. 今晚验证目标判定

### 必须通过

- BAT dry-run 明确 `continuous HLS` 且 `no --gemini`
- 真实直播生成 manifest + combined transcript
- 录制期间无大段缺口
- `source_status` 可解释
- 不出现双路 Gemini 消耗

### 加分通过

- 最终 Markdown 生成成功
- `body_coverage_status` 为 `ok`，或 warning 能准确指出尾段 gap
- `Slides/<BASE>/slides.pdf` 和 `slides.pptx` 生成成功

### 失败但可接受

- Gemini 最终文档因 quota/network 失败，但录制/转写完整
- PPTX 因 `python-pptx` 缺失跳过，但 PDF 成功

### 需要立即停止并回报

- dry-run 显示 stream-stage `--gemini`
- BAT 走了非 continuous HLS 默认路径
- 连续出现 ffmpeg 录制失败
- manifest 没生成
- 输出名 marker 读取失败
