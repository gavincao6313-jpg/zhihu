# Qwen 短视频批量抽取工作流设计 - 2026-05-27

> 目标：面向大量 10 分钟以下短视频，建立一条低 API 调用次数、可恢复、可审计、可扩展到 Batch API 的 Qwen 主线。不要直接继承长视频 sliding-window 流程。

## 0. 结论

短视频需要一条专用工作流，但不是重写所有底层能力。

正确拆法：

```text
Short video URL / local MP4
  -> local preprocess queue
     - download / resolve media
     - ASR transcript
     - keyframes / visual evidence
     - per-video payload manifest
  -> short-video synthesis queue
     - classify one-shot vs pack
     - pack multiple short videos by transcript/frame budget
     - one Qwen request per pack
  -> split outputs
     - parse VIDEO_ID blocks
     - write Markdowns/TTS_<video_id>.md
     - write per-video QC and pack manifest
```

复用现有能力：

- `stream_extractors.py` 的 URL 解析和 `yt-dlp` 路由。
- `zhihuTTS_video.py` 的 ASR、关键帧、payload 语义。
- `utils.call_qwen()` 的 OpenAI-compatible Qwen adapter。
- `scripts/build_stream_markdown.py` 里已经验证过的 Qwen 保真提示词、事实/叙事/QC 思路。

新增能力：

- `preprocess-only` 队列。
- `synthesize-only` 队列。
- 短视频 `packing`。
- 包输出拆分器。
- 包级和视频级 QC。

## 1. 为什么不能直接套长视频流程

长视频 Qwen sliding-window 解决的是三个问题：

1. 单次 Qwen 图片上限约 250 张。
2. 2-3 小时内容在 one-shot 里容易尾段遗忘。
3. 长文本需要先保真抽取，再最终组装。

短视频的主要矛盾不同：

1. 单条 10 分钟以下视频通常不会超过 Qwen 上下文或图片上限。
2. 大批量短视频的成本瓶颈是“一视频一请求”。
3. sliding-window 对短视频会引入额外调用：window note + final assembly，反而浪费。

因此短视频默认路径应是：

```text
single short video -> one-shot Qwen
many short videos  -> packed one-shot Qwen
```

只有当某条短视频异常复杂时，才升级：

```text
complex short video -> single-video one-shot
very dense video    -> fallback to long-video sliding-window
```

## 2. 视频分类策略

第一版使用确定性分类，不让模型决定路线。

### 2.1 short_video

满足以下全部条件：

- `duration_s <= 600`
- `transcript_chars <= 12000`
- `kept_frames <= 32`
- 本地预处理成功

默认进入 packing 队列。

### 2.2 medium_video

满足任一条件：

- `600 < duration_s <= 1800`
- `12000 < transcript_chars <= 40000`
- `32 < kept_frames <= 128`

默认单视频 Qwen one-shot，不参与 packing。原因是 medium video 与其他短视频打包后，容易挤压包预算和输出质量。

### 2.3 long_or_dense_video

满足任一条件：

- `duration_s > 1800`
- `transcript_chars > 40000`
- `kept_frames > 128`

进入现有长视频策略：

- Qwen one-shot 作为低成本尝试。
- 需要完整视觉覆盖时，显式使用 Qwen sliding-window。

### 2.4 manual_override

允许 CLI 覆盖自动分类：

```text
--short-only
--force-pack
--force-one-shot
--force-sliding-window
```

第一版只实现 `--short-only` 和 `--force-one-shot` 即可，避免入口过早膨胀。

## 3. 目录与产物

短视频工作流应避免污染长视频缓存。

建议新增：

```text
runs/short-video/
  preprocess/
    <video_id>.payload.json
    <video_id>.transcript.txt
    <video_id>.frames.json
  packs/
    pack-YYYYMMDD-HHMMSS-001.input.json
    pack-YYYYMMDD-HHMMSS-001.output.md
    pack-YYYYMMDD-HHMMSS-001.manifest.json
  qc/
    <video_id>.qc.json
    pack-YYYYMMDD-HHMMSS-001.qc.json

Markdowns/
  TTS_short_<video_id>.md
```

`video_id` 必须稳定：

- 本地文件：`sha1(relative_path + file_size + mtime)[:12]` + slug。
- URL：`sha1(canonical_url)[:12]` + host slug。
- 如果后续接入 Obsidian，`video_id` 不应依赖标题，因为标题会改。

## 4. 预处理队列

### 4.1 输入

支持两种输入：

```text
python scripts/short_video_pipeline.py preprocess --input-file urls.txt
python scripts/short_video_pipeline.py preprocess --videos-dir Videos/short
```

`urls.txt` 每行一条：

```text
https://www.toutiao.com/video/...
https://www.ixigua.com/...
/absolute/path/to/video.mp4
```

### 4.2 输出 payload schema

每个视频生成一个 payload：

```json
{
  "schema_version": "short-video-payload-v1",
  "video_id": "toutiao-a1b2c3d4e5f6",
  "source": {
    "kind": "url",
    "original": "https://www.toutiao.com/video/...",
    "canonical": "https://www.toutiao.com/video/...",
    "resolved_media_url": "",
    "local_media_path": "Videos/short/toutiao-a1b2c3d4e5f6.mp4"
  },
  "media": {
    "duration_s": 47.167,
    "width": 1920,
    "height": 1080,
    "size_bytes": 13900000
  },
  "transcript": {
    "backend": "sensevoice",
    "chars": 1800,
    "path": "runs/short-video/preprocess/toutiao-a1b2c3d4e5f6.transcript.txt"
  },
  "frames": [
    {
      "ts_s": 12.4,
      "type": "slide",
      "path": "cache/keyframes/toutiao-a1b2c3d4e5f6/frame_00012.jpg",
      "marker": "Frame [00:00:12] type=slide"
    }
  ],
  "classification": {
    "kind": "short_video",
    "reason": "duration<=600, transcript_chars<=12000, kept_frames<=32"
  }
}
```

### 4.3 预处理状态

`.progress.json` 不应再只有 `status=done/failed`。短视频至少需要：

```json
{
  "short_videos": {
    "<video_id>": {
      "preprocess_status": "pending|done|failed",
      "synthesis_status": "pending|packed|done|failed",
      "classification": "short_video|medium_video|long_or_dense_video",
      "pack_id": "",
      "provider": "qwen",
      "api_calls": 0,
      "usage": {},
      "estimated_cost_cny": 0.0,
      "last_error": ""
    }
  }
}
```

不要把短视频状态混进现有长视频 `videos` 字段里，否则后续重跑和统计会混乱。

## 5. Packing 策略

### 5.1 第一版包预算

保守起步：

| 项 | 上限 |
|---|---:|
| 每包视频数 | 8 |
| 每包 transcript chars | 80000 |
| 每视频 frame 数 | 12 |
| 每包总 frame 数 | 96 |
| 每包预估输入 token | 160000 |
| 每包输出 token | 64000 |

说明：

- Qwen 单次图片上限虽然约 250，但短视频 packing 第一版不应贴着上限跑。
- `96` 张图可以给 8 个视频平均 12 张，足够覆盖短视频结构变化。
- 等真实成本和质量稳定后，再把 `pack_total_frames` 提到 128。

### 5.2 装包算法

确定性 First Fit Decreasing：

1. 只选择 `classification.kind == short_video` 且 `synthesis_status == pending` 的 payload。
2. 按 `score = transcript_chars + kept_frames * 600` 从大到小排序。
3. 逐个放入第一个还能容纳它的包。
4. 如果单个视频超过包预算，降级为单视频 one-shot。

### 5.3 帧选择

每个短视频最多选 `12` 张：

1. 保留首帧或开场上下文 1 张。
2. slide/annotation/context 按类型均衡采样。
3. 时间上均匀覆盖。
4. 恢复全包时间顺序时，必须保留 `video_id`，不能只按 timestamp 排。

包内 frame marker 使用：

```text
[VIDEO_ID=toutiao-a1b2c3d4e5f6] Frame [00:00:12] type=slide
```

## 6. Qwen 输入契约

每包只调用一次 Qwen。

输入结构：

```text
SYSTEM / instruction:
  你正在处理一个短视频包。每个 VIDEO 是独立内容，不得互相混写。

PACK MANIFEST:
  pack_id
  video_count
  required output schema

VIDEO 1:
  VIDEO_ID
  title/source
  duration
  transcript
  selected frames

VIDEO 2:
  ...
```

关键要求：

- 每个视频必须输出一个完整 Markdown 块。
- 不允许跨视频合并主题。
- 不允许因为多个视频相似就写“同上”。
- 每个视频必须有 `## 时间线`、`## 关键事实`、`## 可检索细节`、`## 完整逐字稿`。
- 如果视频信息不足，要在该视频块内写 `source_insufficient`，不能污染其他视频。

## 7. Qwen 输出 schema

必须严格使用边界标记：

```markdown
<!-- SHORT_VIDEO_PACK_ID: pack-20260527-001 -->
<!-- VIDEO_ID: toutiao-a1b2c3d4e5f6 -->
# <视频标题或稳定标题>

## 1. 内容概览

## 2. 时间线

### [00:00:00 - 00:00:15] ...

## 3. 关键事实

## 4. 可检索细节

## 5. 视觉证据索引

## 6. 完整逐字稿

<!-- END_VIDEO_ID: toutiao-a1b2c3d4e5f6 -->
```

拆分器只接受完整成对的 `VIDEO_ID` / `END_VIDEO_ID`。

如果 Qwen 漏掉某个视频：

- 包级 QC 标记 `missing_video_id`。
- 未输出视频保持 `synthesis_status=failed`。
- 包内其他完整视频可以落盘，不整包回滚。

## 8. 失败恢复

### 8.1 API 失败

一包 API 失败：

1. 按视频数二分拆包。
2. 每半包重新调用。
3. 如果单视频仍失败，标记该视频失败。

最大重试：

```text
pack API retries: 2
split retries: 2 levels
single video retries: 2
```

### 8.2 输出解析失败

解析失败分三类：

| 问题 | 处理 |
|---|---|
| 缺 `VIDEO_ID` 边界 | 整包失败，二分拆包 |
| 部分视频缺失 | 完整视频落盘，缺失视频重试 |
| 某视频 Markdown 为空/过短 | 只重试该视频 |

### 8.3 可恢复性

每次 API 调用前写：

```text
runs/short-video/packs/<pack_id>.input.json
```

API 返回后立即写：

```text
runs/short-video/packs/<pack_id>.output.md
```

拆分和 QC 完成后写：

```text
runs/short-video/packs/<pack_id>.manifest.json
```

这样中断后可以从 output.md 继续拆分，不需要重复调用 Qwen。

## 9. QC 门禁

### 9.1 包级 QC

必须检查：

- `expected_video_count == parsed_video_count`
- 每个 expected `video_id` 都出现且边界闭合。
- Qwen usage 存在。
- API calls 记录准确。
- 每个视频至少有 H1 和必要章节。

### 9.2 视频级 QC

每个视频检查：

```json
{
  "video_id": "toutiao-a1b2c3d4e5f6",
  "source_status": "full|partial|failed",
  "body_status": "ok|warning|failed",
  "transcript_chars": 1800,
  "body_chars": 1200,
  "body_transcript_ratio": 0.66,
  "timeline_status": "ok",
  "fact_status": "ok",
  "frame_status": "ok",
  "warnings": []
}
```

短视频不要照搬长视频 `body/transcript ratio >= 0.35` 的硬阈值。建议：

- transcript `< 2000 chars`：body 至少 `600 chars`。
- transcript `2000-12000 chars`：body/transcript ratio 至少 `0.25`。
- 如果完整逐字稿附录存在，事实缺失警告应区分“正文吸收不足”和“源文档缺失”。

## 10. CLI 设计

新增一个入口，避免继续扩大 `zhihuTTS.py`：

```text
python scripts/short_video_pipeline.py preprocess --input-file urls.txt
python scripts/short_video_pipeline.py synthesize --provider qwen --pack
python scripts/short_video_pipeline.py run --input-file urls.txt --provider qwen --pack
python scripts/short_video_pipeline.py status
python scripts/short_video_pipeline.py retry-failed --provider qwen
```

第一阶段只实现：

```text
preprocess
synthesize --dry-run
synthesize --provider qwen --pack --max-videos N
status
```

不要第一版就接 Batch API。Batch API 的输入/输出回收复杂度更高，应等 packing schema 稳定后再接。

## 11. 与现有长视频/直播流程的边界

### 不改

- `run_zhihu_live.bat` 默认链路。
- 长视频 Qwen sliding-window 默认策略。
- Gemini provider 默认策略。
- 现有 `Markdowns/TTS_stream-*.md` 命名。

### 可复用

- `utils.call_qwen()`。
- `select_frames()` 的均衡抽样思想，但短视频需要按 `video_id` 分组。
- Qwen NotebookLM prompt 的保真要求。
- deterministic transcript appendix。

### 需要拆出来

当前 `zhihuTTS.py process_video()` 同时做：

```text
preprocess -> build payload -> call Gemini -> write Markdown
```

短视频需要把这些拆成可复用函数：

```text
preprocess_video_to_payload()
build_qwen_short_video_parts()
call_qwen_pack()
split_short_video_pack_output()
write_short_video_markdowns()
```

拆函数时要先做 GitNexus impact 分析，避免破坏现有本地 MP4 批处理。

## 12. 实施阶段

### P0: 设计和 dry-run

目标：不调用 Qwen，也能看到将如何装包。

交付：

- `docs/SHORT_VIDEO_QWEN_WORKFLOW_DESIGN_20260527.md`
- `scripts/short_video_pipeline.py`
- `--preprocess` 产物 schema
- `--synthesize --dry-run` 输出包预算

验收：

- 给 20 个短视频 payload，dry-run 能稳定生成 pack plan。
- 不需要任何 API key。

当前实现入口：

```text
python scripts/short_video_pipeline.py preprocess --input-file urls.txt
python scripts/short_video_pipeline.py preprocess --videos-dir Videos/short
python scripts/short_video_pipeline.py synthesize --dry-run
python scripts/short_video_pipeline.py synthesize --dry-run --write-plan
python scripts/short_video_pipeline.py status
python scripts/short_video_pipeline.py mock-payloads --count 20
```

P0 约束：

- `synthesize` 不带 `--dry-run` 会直接失败，避免误以为已经接入 Qwen 实调。
- `mock-payloads` 只用于离线验证 packing，不代表真实 ASR/关键帧质量。
- URL 预处理可走 `--extractor auto|ytdlp|playwright|direct`，但真正稳定性要用目标平台样本验证。

### P1: Qwen packing 实调

目标：一个 pack 一次 Qwen，拆出多个 Markdown。

交付：

- `call_qwen_pack()`
- output splitter
- pack manifest
- video QC

验收：

- 5 个短视频一包。
- 1 次 Qwen 调用。
- 5 个 Markdown 全部落盘。
- 缺失 `VIDEO_ID` 时能重试/拆包。

当前实现入口：

```text
python scripts/short_video_pipeline.py call-pack \
  --plan runs/short-video/packs/pack-<ts>.plan.json \
  --pack-index 1 \
  --mock-output \
  --split

python scripts/short_video_pipeline.py call-pack \
  --plan runs/short-video/packs/pack-<ts>.plan.json \
  --pack-index 1 \
  --split

python scripts/short_video_pipeline.py split-pack \
  --input-json runs/short-video/packs/pack-<ts>-001.input.json \
  --output-md runs/short-video/packs/pack-<ts>-001.output.md
```

说明：

- `--mock-output` 不调用 Qwen，只生成确定性 Markdown，用于验证拆分和 QC。
- 不带 `--mock-output` 时必须设置 `DASHSCOPE_API_KEY`，并显式调用 Qwen。
- `call-pack --split` 会写：
  - `runs/short-video/packs/<pack_id>.input.json`
  - `runs/short-video/packs/<pack_id>.output.md`
  - `runs/short-video/packs/<pack_id>.manifest.json`
  - `Markdowns/TTS_short_<video_id>.md`
  - `runs/short-video/qc/<pack_id>.qc.json`

### P2: 失败恢复和调度

目标：大量短视频可断点续跑。

交付：

- `.progress.json short_videos`
- `retry-failed`
- output.md 复用，不重复调用 Qwen
- 包失败二分拆包

验收：

- 中断后重跑不会重复处理已完成视频。
- 已有 pack output 可直接 split。

### P3: 成本统计和 Batch API 准备

目标：决定是否值得接 Batch File API。

交付：

- usage aggregation
- estimated_cost_cny
- pack 平均成本报告
- Batch input/export schema 草案

验收：

- 能回答每 100 个短视频的 Qwen 调用次数、token、估算成本。

## 13. 初始默认参数

```json
{
  "short_max_duration_s": 600,
  "short_max_transcript_chars": 12000,
  "short_max_frames": 32,
  "pack_max_videos": 8,
  "pack_max_transcript_chars": 80000,
  "pack_max_frames": 96,
  "per_video_max_frames": 12,
  "provider": "qwen",
  "model": "qwen3.6-flash",
  "max_retries": 2,
  "max_continuations": 1,
  "qwen_thinking": false
}
```

## 14. 不做事项

第一版明确不做：

- 不把短视频接进 `run_zhihu_live.bat`。
- 不默认启用 Gemini。
- 不对短视频默认 sliding-window。
- 不做多 API key 轮换。
- 不把 Batch API 作为第一版主路径。
- 不把多个短视频合成一个最终总文档；每个视频必须有独立 Markdown。

## 15. 当前风险

| 风险 | 级别 | 应对 |
|---|---|---|
| Qwen 混写多个视频内容 | 高 | 强制 VIDEO_ID 边界、拆分 QC、缺失视频单独重试 |
| 一包过大导致输出截断 | 中 | 第一版保守 8 视频/80k chars/96 frames，continuation 限制为 1 |
| 短视频过短，模型生成空泛总结 | 中 | 要求完整逐字稿、关键事实、可检索细节；正文最小长度 QC |
| URL 平台解析不稳定 | 中 | 预处理阶段与 synthesis 分离，URL 失败不消耗 Qwen |
| 与长视频 `.progress.json` 混乱 | 高 | 独立 `short_videos` namespace |

## 16. 推荐下一步

下一步不要直接写 Qwen API 调用。

先实现 P0：

1. 新建 `scripts/short_video_pipeline.py`。
2. 只做 `preprocess` 和 `synthesize --dry-run`。
3. 从已有 payload 或 mock payload 生成 pack plan。
4. 用 10-20 个短视频样本验证分类和装包是否合理。

P0 通过后，再接 `utils.call_qwen()` 做 P1 实调。
