# Live Stream A/B Test Prep - 2026-05-26

目标：今晚同一个知乎直播间同时启动两个 Windows 进程，分别用 Gemini 3.5 Flash 与 Qwen3.6-Flash 做 final NotebookLM synthesis，对比实时直播链路的采集稳定性与最终文档质量。

## 1. 关键原则

- 两个进程都走 `run_zhihu_live.bat`，采集阶段只做 continuous HLS + ASR，不调用 Gemini/Qwen。
- Gemini/Qwen 只在直播结束后的 Step 3 final synthesis 调用。
- 两个进程必须使用不同输出名，建议固定为：
  - `live-ab-20260526-gemini`
  - `live-ab-20260526-qwen`
- 今晚正式 A/B 一律使用 `--fair-ab`，BAT 会自动把 Gemini/Qwen final synthesis 都限制为同样的 128 帧视觉输入。
- 双进程会录制两份 HLS，CPU/磁盘/网络压力约等于单进程的 2 倍；如果机器明显吃紧，改用“单采集、双合成”方案。
- 不要使用 `--resume`。continuous HLS 默认入口会拒绝 `--resume`。

## 2. 开播前 30 分钟预检

在 Windows 仓库目录执行：

```bat
cd /d d:\zhihu\zhihu_file
git pull
d:\zhihu\zhihu_file\.venv-sensevoice\Scripts\python.exe -m pip install -r requirements.txt
```

检查登录态：

```bat
d:\zhihu\zhihu_file\.venv-sensevoice\Scripts\python.exe scripts\check_auth.py zhihu_auth_state.json
```

如果失败：

```bat
d:\zhihu\zhihu_file\.venv-sensevoice\Scripts\python.exe login_save_auth.py
```

检查工具：

```bat
where ffmpeg
where ffprobe
```

检查 dry-run。两个 CMD 分别执行：

```bat
set GEMINI_API_KEY=your_gemini_key
set DASHSCOPE_API_KEY=
run_zhihu_live.bat "<直播间URL>" live-ab-20260526-gemini --provider gemini --fair-ab --dry-run
```

```bat
set DASHSCOPE_API_KEY=your_dashscope_key
set GEMINI_API_KEY=
run_zhihu_live.bat "<直播间URL>" live-ab-20260526-qwen --provider qwen --fair-ab --dry-run
```

dry-run 应确认：

- `采集模式: continuous HLS recorder + async consumer`
- `直播转写模型 API: disabled`
- 两个窗口都显示 `公平 A/B 模式: enabled (max frames 128)`
- Gemini 窗口显示 `最终 Provider: gemini` 和 `A/B max frames: 128`
- Qwen 窗口显示 `最终 Provider: qwen`、`Qwen max frames: 128` 和 `A/B max frames: 128`
- Step 3 是 `build_stream_markdown.py --provider ...`
- Step 4 是 `extract_slides.py --stream-base ...`

## 3. 正式启动双进程

Gemini CMD：

```bat
cd /d d:\zhihu\zhihu_file
set GEMINI_API_KEY=your_gemini_key
set DASHSCOPE_API_KEY=
run_zhihu_live.bat "<直播间URL>" live-ab-20260526-gemini --provider gemini --fair-ab
```

Qwen CMD：

```bat
cd /d d:\zhihu\zhihu_file
set DASHSCOPE_API_KEY=your_dashscope_key
set GEMINI_API_KEY=
run_zhihu_live.bat "<直播间URL>" live-ab-20260526-qwen --provider qwen --fair-ab
```

建议两个命令在 30 秒内启动，记录两个窗口日志文件名。

## 4. 直播中监控

重点看两个窗口/日志是否都有：

- `[1/4] 开始直播转写`
- `continuous HLS`
- 每 60 秒左右持续生成 chunk
- 没有 Playwright 登录失效、ffmpeg 退出、HLS segment 长时间不增长

如果窗口关了，后台任务仍在，按日志路径重新 tail：

```bat
powershell Get-Content -Wait -Tail 80 "logs\run-live-ab-20260526-gemini.log"
powershell Get-Content -Wait -Tail 80 "logs\run-live-ab-20260526-qwen.log"
```

## 5. 直播结束后的预期产物

Gemini：

```text
runs\stream-live-ab-20260526-gemini-*.gemini35.final-qc.json
Markdowns\TTS_stream-live-ab-20260526-gemini-gemini35.md
Slides\live-ab-20260526-gemini\slides.pdf
```

Qwen：

```text
runs\stream-live-ab-20260526-qwen-*.qwen.final-qc.json
Markdowns\TTS_stream-live-ab-20260526-qwen-qwen.md
Slides\live-ab-20260526-qwen\slides.pdf
```

如果 final synthesis 被跳过，按日志里的手动命令重跑。常见原因：

- Gemini 未设置 `GEMINI_API_KEY`
- Qwen 未设置 `DASHSCOPE_API_KEY`
- Qwen 环境缺 `openai` 包，需要重新执行 `pip install -r requirements.txt`
- Gemini 环境缺 `google-genai` 包，需要重新执行 `pip install -r requirements.txt`

## 6. 对比记录项

每个 provider 至少记录：

- 开始/结束时间，日志文件路径
- chunks 数、timeline duration、gaps、failed chunks、silent chunks
- transcript chars、frames、selected frames、dropped frames
- `synthesis_provider` / `synthesis_model`
- `body_coverage_status` / `body_tail_gap_s`
- Markdown 正文质量：章节完整度、尾部覆盖、视觉内容提取、术语准确度
- Qwen `provider_usage.api_calls` 和 token usage

## 7. 停止条件

出现以下任一情况，停止对应进程并保留日志：

- dry-run 显示采集阶段会调用模型 API。
- 两个进程同时出现 ffmpeg/HLS segment 停止增长超过 3 分钟。
- 登录态失效或直播页面无法访问。
- Qwen final QC 里 selected frames 超过 256。
- final synthesis 连续 429 或重试耗尽。

## 8. 低风险替代方案

如果双进程导致机器负载过高，改成单采集：

```bat
run_zhihu_live.bat "<直播间URL>" live-ab-20260526-source --no-gemini
```

直播结束后，用同一个 source base 做双合成：

```bat
python scripts\build_stream_markdown.py --base live-ab-20260526-source --provider gemini --output-label gemini35 --max-frames 128 --max-retries 2 --max-continuations 2
python scripts\build_stream_markdown.py --base live-ab-20260526-source --provider qwen --output-label qwen --qwen-max-frames 128 --max-frames 128 --max-retries 2 --max-continuations 2
```
