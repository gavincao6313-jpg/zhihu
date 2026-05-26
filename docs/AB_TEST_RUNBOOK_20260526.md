# Gemini 3.5 Flash vs Qwen A/B Test Runbook - 2026-05-26

> 目标：同一份回放/直播转写产物，用 Gemini 3.5 Flash 和 Qwen3.6-Flash 分别生成 NotebookLM Markdown，比较正文质量、时间覆盖、知识点命中和成本。

## 0. 先更新依赖

Qwen provider 需要 OpenAI-compatible SDK：

```bat
d:\zhihu\zhihu_file\.venv-sensevoice\Scripts\python.exe -m pip install -r requirements.txt
```

如果只想单独安装：

```bat
d:\zhihu\zhihu_file\.venv-sensevoice\Scripts\python.exe -m pip install openai
```

## 1. 环境变量

Gemini：

```bat
set GEMINI_API_KEY=your_gemini_key
```

Qwen：

```bat
set DASHSCOPE_API_KEY=your_dashscope_key
```

可选覆盖模型：

```bat
set GEMINI_MODEL=gemini-3.5-flash
set QWEN_MODEL=qwen3.6-flash
```

## 2. 回放视频 A/B

前提：回放视频已经通过 stream/replay 流程生成 `runs/stream-<BASE>_chunk*.global-transcript.txt` 和对应 payload。

注意：`--base` 只传 `<BASE>`，不要带前缀 `stream-`。例如文件是：

```text
runs/stream-ab-replay-20260522_chunk001_0s-....global-transcript.txt
```

命令应传：

```bat
--base ab-replay-20260522
```

### 2.1 Dry-run

Gemini：

```bat
python scripts\build_stream_markdown.py ^
  --base <BASE> ^
  --provider gemini ^
  --output-label gemini35 ^
  --max-retries 2 ^
  --max-continuations 2 ^
  --dry-run
```

Qwen：

```bat
python scripts\build_stream_markdown.py ^
  --base <BASE> ^
  --provider qwen ^
  --qwen-max-frames 128 ^
  --max-retries 2 ^
  --max-continuations 2 ^
  --dry-run
```

### 2.2 实调

Gemini：

```bat
python scripts\build_stream_markdown.py ^
  --base <BASE> ^
  --provider gemini ^
  --output-label gemini35 ^
  --max-retries 2 ^
  --max-continuations 2
```

Qwen：

```bat
python scripts\build_stream_markdown.py ^
  --base <BASE> ^
  --provider qwen ^
  --qwen-max-frames 128 ^
  --max-retries 2 ^
  --max-continuations 2
```

### 2.3 输出文件

Gemini：

```text
Markdowns\TTS_stream-<BASE>-gemini35.md
runs\stream-<BASE>-<run_ts>.gemini35.final-qc.json
```

Qwen：

```text
Markdowns\TTS_stream-<BASE>-qwen.md
runs\stream-<BASE>-<run_ts>.qwen.final-qc.json
```

## 3. 今晚直播双进程 A/B

双进程会对同一个直播间分别录制两份 continuous HLS，再分别 final synthesis。这样采集链路也参与 A/B；机器负载会翻倍。

### 3.1 Gemini 进程

新开一个 CMD：

```bat
set GEMINI_API_KEY=your_gemini_key
run_zhihu_live.bat "<直播间URL>" live-ab-gemini --provider gemini
```

预期：

- 采集阶段不调用模型 API。
- final synthesis 使用 `gemini-3.5-flash`。
- 输出：`Markdowns\TTS_stream-live-ab-gemini.md`。

### 3.2 Qwen 进程

另开一个 CMD：

```bat
set DASHSCOPE_API_KEY=your_dashscope_key
run_zhihu_live.bat "<直播间URL>" live-ab-qwen --provider qwen --qwen-max-frames 128
```

预期：

- 采集阶段不调用模型 API。
- final synthesis 使用 `qwen3.6-flash`。
- 输出：`Markdowns\TTS_stream-live-ab-qwen-qwen.md`。

`-qwen` 后缀来自 finalizer 的默认 Qwen output label，用于避免同 base 覆盖。

## 4. 低风险替代方案：单采集、双合成

如果担心双进程采集造成机器负载、网络或登录态压力，推荐只录制一次：

```bat
run_zhihu_live.bat "<直播间URL>" live-ab-source --no-gemini
```

结束后用同一个 `<BASE>` 跑两次 final synthesis：

```bat
python scripts\build_stream_markdown.py --base live-ab-source --provider gemini --output-label gemini35 --max-retries 2 --max-continuations 2
python scripts\build_stream_markdown.py --base live-ab-source --provider qwen --qwen-max-frames 128 --max-retries 2 --max-continuations 2
```

这个方案只比较 synthesis 模型质量，不比较采集稳定性。

## 5. 对比指标

每组输出至少记录：

- provider / model
- chunks / timeline duration / transcript chars / frames
- selected frames / dropped frames
- body_coverage_status / body_tail_gap_s
- 正文字符数，不含附录
- 最后章节时间戳
- 尾部 20 分钟是否覆盖
- 关键知识点命中
- Qwen usage tokens / api_calls / 账单成本

## 6. 停止条件

立即停止对应 provider：

- dry-run 显示采集阶段会调用模型 API。
- Qwen selected frames 超过 256。
- 429 或限流连续重试后仍失败。
- final-qc 显示 `source_status=partial` 且无法解释。
- 输出覆盖到尾部之前出现大段截断。
