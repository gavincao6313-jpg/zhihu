# API Provider Optimization Plan - 2026-05-26

> 目标：在不破坏已验证 Gemini/直播链路的前提下，引入 Qwen provider，解决 Gemini Free tier RPD 对大批量视频，尤其是短视频的吞吐限制。

## 0. 结论

不做“一次性迁移”。做 provider 扩展：

- Gemini 保留为默认 provider，继续服务已验证链路。
- Qwen 作为显式 opt-in provider：`--provider qwen`。
- 先在 `scripts/build_stream_markdown.py` 试点，不先改 `zhihuTTS.py` 主批处理。
- 短视频吞吐的长期解法是“本地预处理队列 + API 合成队列 + 短视频打包”，不是简单把每个视频从 Gemini 单请求换成 Qwen 单请求。

## 1. 已确认事实

### Gemini

- 项目当前使用 Gemini Free tier，额度按 RPM / TPM / RPD 共同限制。
- 限制按 Google Cloud / AI Studio project 计算，不按单个 API key 计算。
- `gemini-3.5-flash` Free tier 仍要按项目内记录的 10 RPM / 250k TPM / 250 RPD 设计。
- 已验证直播主链路应保持：采集阶段不调用 Gemini，最终 only one-shot synthesis。

参考：<https://ai.google.dev/gemini-api/docs/rate-limits>

### Qwen / Dashscope

- `qwen3.6-flash` 支持文本、图像、视频输入，1M 上下文，64k 最大输出。
- OpenAI-compatible endpoint 可用：`https://dashscope.aliyuncs.com/compatible-mode/v1`。
- 视觉理解模型表显示 Qwen3.6 系列单次最大图片数 256。
- 限流按阿里云主账号汇总，不按 API key 扩容；但不存在 Gemini Free tier 的每日 RPD 硬墙。
- WIN 文档中的 `<0.8 元/百万 tokens` 价格估算不能直接采用。官方价格页显示 `qwen3.6-flash` 是分档计费，例如 0-256K 输入档约为输入 1.2 元/百万、输出 7.2 元/百万，256K-1M 档更高。实际预算必须记录 usage tokens 后按账单校准。
- Batch File API 可作为后续低优先级 backlog 通道，官方标注费用为实时调用 50%，但应先完成实时 provider 试点。

参考：

- 视觉理解：<https://help.aliyun.com/zh/model-studio/vision-model>
- OpenAI 兼容：<https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope>
- 价格：<https://help.aliyun.com/zh/model-studio/model-pricing>
- 限流：<https://help.aliyun.com/zh/model-studio/rate-limit>
- Batch File：<https://help.aliyun.com/zh/model-studio/openai-compatible-batch-file-input/>

## 2. 目标架构

```text
Video / Live / Replay
  -> Local preprocess
     - ASR transcript
     - keyframes / slides
     - payload cache
     - deterministic transcript appendix
  -> Synthesis job
     - provider: gemini | qwen
     - model
     - frame budget
     - retry / continuation caps
     - estimated request body size
     - estimated and actual token/cost record
  -> Provider adapter
     - Gemini SDK path
     - Qwen OpenAI-compatible path
  -> QC
     - source coverage
     - body coverage
     - deterministic appendices
     - provider usage
```

核心原则：

- 本地预处理可以高吞吐执行，不消耗 LLM API。
- API synthesis 必须变成显式、可预算、可排队的后处理任务。
- Provider adapter 只处理 API 差异，不改变上游 transcript/keyframe 语义。
- Frame selection 必须 provider-aware；Qwen 不能沿用 Gemini 的 3000 image hard limit。

## 3. P0 试点：直播 finalizer 支持 Qwen

首个改造目标：`scripts/build_stream_markdown.py`。

原因：

- 它已经是后处理 one-shot synthesis，天然适合切 provider。
- 已有 `--dry-run`、`--mock-gemini-text`、`--max-retries`、`--max-continuations`、final QC。
- 可用 2026-05-25 Windows 实播产物复测，不需要重新录制。
- 不碰 `run_zhihu_live.bat` 默认行为，避免引入 default-on 新 API 调用。

预期 CLI：

```bash
python scripts/build_stream_markdown.py \
  --base <BASE> \
  --provider qwen \
  --qwen-max-frames 128 \
  --max-retries 2 \
  --max-continuations 2
```

默认行为：

- `--provider gemini` 为默认，保持兼容。
- `--provider qwen` 时读取 `DASHSCOPE_API_KEY`。
- `QWEN_MODEL` 可覆盖默认模型，默认 `qwen3.6-flash`。
- Qwen 默认先关闭 thinking 或使用低预算；不要默认开启大 thinking budget。
- Qwen 默认 frame cap 先设 128，硬上限 256；通过 CLI 显式提高。

## 4. Provider Adapter 设计

新增共享函数建议放在 `utils.py`，但正式修改前必须跑 GitNexus impact。

建议接口：

```python
def call_qwen(
    client,
    parts: list,
    label: str,
    *,
    model: str = "qwen3.6-flash",
    enable_thinking: bool = False,
    thinking_budget: int = 4096,
    max_retries: int = 2,
    retry_delay: int = 10,
    max_continuations: int = 2,
    continuation_cooldown: int = 2,
) -> dict:
    ...
```

返回值不要只返回 `str | None`。建议返回结构化结果：

```python
{
  "text": "...",
  "provider": "qwen",
  "model": "qwen3.6-flash",
  "api_calls": 1,
  "finish_reason": "stop",
  "usage": {
    "input_tokens": 0,
    "output_tokens": 0,
    "total_tokens": 0
  },
  "estimated_cost_cny": null
}
```

这样后续 Gemini 也可以逐步统一为结构化返回，解决当前 `.progress.json` 只记 calls、不记 token/cost 的问题。

Qwen parts 转换规则：

- `str` -> OpenAI content text item。
- Google `types.Part(inline_data=Blob(...))` -> Base64 data URL image item。
- 用 duck typing 检测 `inline_data`，避免 adapter 强绑定 Google SDK 类型。
- 对无法识别的 part fail fast，不要静默丢帧。

Qwen continuation：

- `finish_reason == "length"` 才续写。
- 续写时把 assistant content 放回 `messages`，再追加 user `"继续"`。
- 第一版不传回 `reasoning_content`，除非开启 `preserve_thinking` 并确认成本可控。
- 所有 continuation 计入 `api_calls`。

## 5. Frame Budget 设计

Gemini 和 Qwen 的 frame policy 分离：

| Provider | 默认 frame cap | 硬上限 | 说明 |
|---|---:|---:|---|
| Gemini | 当前逻辑 | 3000 | 保持现状，避免影响已验证产物 |
| Qwen | 128 | 256 | 先保守试点，避免 499 帧直播直接失败 |

Qwen frame selection 优先级：

1. `type=slide`
2. `type=annotation`
3. context frames 按时间均匀抽样

所有被丢弃的帧要写入 QC：

```json
{
  "provider": "qwen",
  "frame_policy": {
    "total_frames": 499,
    "selected_frames": 128,
    "dropped_frames": 371,
    "cap": 128
  }
}
```

## 6. Budget Ledger

新增或扩展 synthesis manifest，记录每次 API synthesis：

```json
{
  "provider": "qwen",
  "model": "qwen3.6-flash",
  "api_calls": 1,
  "max_retries": 2,
  "max_continuations": 2,
  "input_text_chars": 55447,
  "frames_total": 499,
  "frames_selected": 128,
  "image_bytes_selected": 12345678,
  "usage": {
    "input_tokens": 0,
    "output_tokens": 0,
    "total_tokens": 0
  },
  "estimated_cost_cny": null,
  "rate_limit_warnings": []
}
```

成本估算第一版可以保守：

- 如果 API response 有 usage，则记录真实 usage。
- 如果没有 usage，则只记录 chars/frames/bytes，不假装精确。
- 不把 WIN 文档的低价估算写进代码常量。

## 7. P1：本地 MP4 预处理与合成解耦

当前短视频吞吐瓶颈来自 `zhihuTTS.py` 把本地预处理和 Gemini synthesis 串在同一个 `process_video()` 里。

P1 目标：

- 增加“preprocess-only”模式：只生成 transcript/keyframes/payload，不调用任何 LLM。
- 增加“synthesize-only”模式：读取已存在 payload，按 provider 执行 final synthesis。
- `.progress.json` 区分：
  - `preprocess_status`
  - `synthesis_status`
  - `provider`
  - `api_calls`
  - `usage`
  - `estimated_cost_cny`

这样 Windows 可以批量跑本地 ASR 和 keyframes，API synthesis 由预算队列慢慢消化。

## 8. P2：短视频打包合成

短视频不应长期保持“一视频一请求”。设计一个 packing 层：

```text
pending short videos
  -> pack by chars/frame budget
  -> one Qwen request
  -> output separated by video_id
  -> split result into Markdowns/TTS_<video>.md
```

包内约束建议：

- 每包最多 5-10 个短视频。
- 总 transcript chars 上限先设 80k。
- 每视频最多 8-16 张图。
- 每包总图数不超过 128。
- 输出必须按固定 schema：

```markdown
<!-- VIDEO_ID: xxx -->
# xxx
...
<!-- END_VIDEO_ID: xxx -->
```

失败恢复：

- 一包失败时二分拆包重试。
- 某个视频解析失败时只标记该视频，不整批回滚。
- 打包模式第一版只支持短视频，不支持直播和长视频。

## 9. P3：Qwen Batch File API

Batch 适合 backlog，不适合实时直播后立即出文档。

进入条件：

- P0 Qwen 实时 provider 验证通过。
- P1 preprocess/synthesize 队列完成。
- P2 packing schema 稳定。

Batch 输出必须可恢复：

- batch job id 写入 manifest。
- 每个 request key 使用稳定 video_id。
- 结果落地后再拆分 markdown。
- 支持重新拉取和断点恢复。

## 10. 验证计划

P0 验证顺序：

1. `--dry-run --provider qwen`：确认不调用 API，只输出预算和 frame policy。
2. `--mock-gemini-text` 等价路径继续可用，确认 Qwen provider 参数不破坏离线 QC。
3. 小样本 Qwen 实调：`--qwen-max-frames 16 --max-continuations 0`。
4. 2026-05-25 实播完整产物 Qwen 实调：先 128 frames，再视质量提高到 256。
5. 对比 Gemini/Qwen：
   - body coverage
   - 正文字符数
   - 章节时间覆盖
   - 关键知识点命中
   - NotebookLM 检索可用性
   - 成本和调用次数

代码验证要求：

- 修改 `utils.py` 前：`gitnexus impact call_gemini upstream`。
- 修改 `scripts/build_stream_markdown.py::main` 前：`gitnexus impact main upstream` 并用 file path 消歧。
- 修改 frame selection 前：`gitnexus impact select_frames upstream`。
- 提交前：`gitnexus detect_changes`。
- L2/L3 核心改动需外部 AI review。

## 11. 暂不做的事

- 不把 `run_zhihu_live.bat` 默认 provider 改成 Qwen。
- 不在采集阶段引入任何 provider API 调用。
- 不直接改 `zhihuTTS.py` 批处理主循环。
- 不默认开启 Qwen thinking 大预算。
- 不做多 API key 轮换；Gemini/Qwen 都不是按 key 简单扩容。
- 不把 Batch API 作为第一版主路径。

## 12. 建议执行顺序

1. 合并远端 `main` 前先处理本地 dirty worktree，避免覆盖现有改动。
2. P0-A：在 `utils.py` 新增 Qwen adapter 与结构化返回。
3. P0-B：在 `scripts/build_stream_markdown.py` 增加 `--provider qwen`、Qwen client、Qwen frame cap、provider usage manifest。
4. P0-C：用 dry-run/mock/small-qwen/full-qwen 四级验证。
5. P1：拆本地 MP4 preprocess-only / synthesize-only。
6. P2：实现短视频 packing。
7. P3：评估并接入 Batch File API。
