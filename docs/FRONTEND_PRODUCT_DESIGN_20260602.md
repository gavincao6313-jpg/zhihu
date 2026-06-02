# zhihu 前端产品化功能设计

日期：2026-06-02

## 1. 目标

当前 zhihu 是后端脚本集合：用户通过 BAT、Python CLI、日志、`runs/`、`Markdowns/`、`Slides/` 手动判断流程是否成功。前端目标不是“给脚本套几个按钮”，而是把整个视频/直播处理过程变成一个可观察、可恢复、可审计的软件功能。

前端必须覆盖三类输入：

- 本地 MP4 文件导入
- 回放视频/回放 URL 输入
- 直播流 URL 输入

前端必须全程可视化：

- 启动过程
- 运行记录
- 中间产物
- QC 记录
- 关键帧
- 逐字稿
- 最终 Markdown 输出

## 2. 产品原则

1. **先做工作台，不做展示页。** 第一屏直接是任务创建、运行监控和产物浏览，不做 landing page。
2. **前端只展示真实状态，不编造进度。** 进度来自 manifest、chunk 文件、日志、QC JSON、Markdown 文件是否存在。
3. **运行对象统一抽象为 Run。** MP4、回放、直播只是 source_type 不同，后续都进入同一个 Run 工作台。
4. **产物优先于日志。** 日志是调试入口；用户主要看“已经生成了什么、质量如何、还能做什么”。
5. **每一步必须可定位到文件。** 前端展示项都应能打开或复制本地相对路径。
6. **默认保护成本。** Gemini/Qwen 调用、滑动窗口、重跑、续跑必须显示预算和调用次数预估。

## 3. 信息架构

### 3.1 顶层导航

- `Sources`：输入源管理
- `Runs`：运行记录列表
- `Run Detail`：单次运行工作台
- `Artifacts`：跨运行产物浏览
- `Settings`：模型、路径、环境、Windows 启动配置

P0 可以只做 `Runs` + `Run Detail`，输入源创建放在同一页顶部。

### 3.2 第一屏布局

第一屏建议采用左右分栏：

- 左侧：任务创建和最近运行列表
- 右侧：当前选中 Run 的流程时间线与关键状态

不使用大 hero，不做营销式页面。界面应该像一个工程控制台：紧凑、清晰、可扫描。

## 4. 核心页面设计

### 4.1 任务创建区

支持三种 source card。

#### 本地 MP4

字段：

- 文件路径或拖拽导入
- 输出 base name
- 转写 backend：`sensevoice` / `faster-whisper` / `auto`
- 是否只预处理
- 是否生成 Slides PDF/PPTX
- 最终模型：Gemini / Qwen / 不合成

主要动作：

- `创建任务`
- `开始处理`
- `仅生成预检`

#### 回放视频

字段：

- 回放 URL
- extractor：auto / ytdlp / playwright
- cookie/auth state
- 输出 base name
- 是否下载为本地 MP4
- 是否直接进入分片转写

主要动作：

- `探测 URL`
- `下载/解析`
- `开始处理`

#### 直播流 URL

字段：

- 直播间 URL
- auth state 状态
- 输出 base name
- 启动方式：前台 / 后台 / WIN START_LIVE
- chunk duration
- provider：Gemini / Qwen / none
- Qwen sliding-window 开关
- no-gemini 开关

主要动作：

- `检查登录态`
- `Dry Run`
- `启动直播转写`
- `结束后补合成`

### 4.2 Runs 列表

每个 Run 显示为一行或紧凑卡片：

- Run 名称 / base
- source type：MP4 / replay / live
- 状态：created / probing / recording / transcribing / synthesizing / completed / warning / failed
- 开始时间、结束时间、耗时
- chunks 数
- transcript chars
- frames 数
- final QC 状态
- final Markdown 是否存在
- provider/model
- warnings 数

筛选：

- source type
- 状态
- provider
- 有无 warning
- 日期

排序：

- 最近运行
- 警告优先
- 处理耗时
- transcript chars

### 4.3 Run Detail 工作台

Run Detail 是核心页面，分成 6 个标签页。

#### Overview

顶部状态条：

- 当前阶段
- 是否仍在运行
- 最新日志时间
- source_status
- body_coverage_status
- warnings count
- final Markdown path

流程时间线：

1. Source created
2. URL/file probe
3. Stream capture / download
4. Chunk transcription
5. Keyframe extraction
6. Merge chunks
7. Final synthesis
8. QC
9. Markdown ready

每个节点显示：

- 状态：pending / running / done / warning / failed
- 产物数量
- 最后更新时间
- 相关文件入口

#### Logs

展示：

- BAT/worker log
- Python stdout/stderr
- 最新错误摘要
- 可搜索日志
- 按阶段过滤日志

P0 可先读取 `logs/*.log`；如果没有 logs，则从 manifest、chunk report、QC JSON 推导。

#### Chunks

表格字段：

- chunk index
- start time
- duration
- transcript chars
- segments
- frames
- reextracts
- backend
- slice kept
- payload path
- transcript path
- report path

功能：

- 点击 chunk 查看 transcript
- 点击 payload 查看 JSON 摘要
- 点击 frames 查看该 chunk 的关键帧
- 标出 failed/silent/skipped chunk

#### Keyframes

关键帧画廊：

- 时间轴缩略图
- frame type：slide / annotation / context
- timestamp
- source chunk
- 图片路径

功能：

- 按类型过滤
- 按时间跳转
- 点击放大
- 显示进入 Qwen/Gemini 的 frame policy：selected / dropped

#### Transcript

逐字稿视图：

- 完整 transcript
- chunk 边界
- 时间戳导航
- 搜索关键词
- 点击时间跳到对应 chunk/keyframe

P0 读取：

- `runs/stream-<base>-<ts>.combined-transcript.txt`
- 或所有 `runs/stream-<base>_chunk*.global-transcript.txt`

#### QC

QC 面板读取 final-qc JSON，展示：

- source_status
- source_type
- timeline_end_s
- body_tail_gap_s
- body_coverage_status
- frame_count
- frame_timestamp_qc
- qwen_window_policy
- qwen_fact_retention_qc
- qwen_narrative_retention_qc
- qwen_timeline_qc
- warnings
- usage / API calls / token usage

展示方式：

- 顶部红黄绿状态
- warnings 独立列表
- frame coverage 小图
- Qwen windows 时间分布图
- fact/narrative retention 通过率

#### Final Markdown

Markdown 工作台：

- 最终 MD 预览
- 原始 Markdown 文本
- 文件路径
- provider/model
- output label
- QC summary
- 下载/打开文件
- 与另一 provider 输出对比

对比视图：

- Gemini vs Qwen
- one-shot vs sliding-window
- 历史版本 vs 当前版本

## 5. 数据模型

### 5.1 Run

```json
{
  "id": "live_20260601_医疗行业AI转型一应用",
  "base": "live_20260601_医疗行业AI转型一应用",
  "source_type": "live",
  "status": "completed",
  "created_at": "2026-06-01T20:01:48+08:00",
  "updated_at": "2026-06-01T22:50:14+08:00",
  "provider": "qwen",
  "model": "qwen3.6-plus",
  "synthesis_pass": "sliding-window",
  "paths": {
    "manifest_json": "runs/stream-<base>-<ts>.manifest.json",
    "manifest_md": "runs/stream-<base>-<ts>.manifest.md",
    "combined_transcript": "runs/stream-<base>-<ts>.combined-transcript.txt",
    "final_qc": "runs/stream-<base>-<ts>.<label>.final-qc.json",
    "markdown": "Markdowns/TTS_stream-<base>-<label>.md",
    "slides_pdf": "Slides/<base>/slides.pdf"
  },
  "metrics": {
    "chunks": 170,
    "transcript_chars": 51551,
    "frames": 436,
    "warnings": 0
  }
}
```

### 5.2 Artifact

```json
{
  "id": "artifact-id",
  "run_id": "live_20260601_...",
  "type": "final_qc",
  "path": "runs/stream-...final-qc.json",
  "created_at": "2026-06-01T22:50:04+08:00",
  "status": "ok",
  "summary": {
    "warnings": [],
    "source_status": "full"
  }
}
```

### 5.3 Pipeline Step

```json
{
  "key": "final_synthesis",
  "label": "Final synthesis",
  "status": "done",
  "started_at": "2026-06-01T22:50:04+08:00",
  "ended_at": "2026-06-01T22:55:00+08:00",
  "artifacts": ["final_qc", "markdown"],
  "warnings": []
}
```

## 6. 后端适配边界

前端不要直接解析所有文件名规则。需要一个轻量 backend/indexer。

### 6.1 P0 后端能力

新增一个 `web_api` 或 `scripts/run_indexer.py`，负责扫描本地目录：

- `runs/`
- `Markdowns/`
- `Slides/`
- `logs/`
- `Videos/`

输出统一 JSON：

- runs list
- run detail
- artifacts list
- chunk list
- QC summary
- markdown content
- transcript content
- keyframe image paths

### 6.2 推荐 API

```text
GET  /api/runs
GET  /api/runs/{id}
GET  /api/runs/{id}/chunks
GET  /api/runs/{id}/artifacts
GET  /api/runs/{id}/qc
GET  /api/runs/{id}/transcript
GET  /api/runs/{id}/markdown
GET  /api/runs/{id}/keyframes
POST /api/sources/probe
POST /api/runs
POST /api/runs/{id}/start
POST /api/runs/{id}/synthesize
POST /api/runs/{id}/extract-slides
```

P0 可以只实现 GET，先把现有产物可视化；P1 再接启动/控制。

## 7. P0 页面范围

P0 不碰真实启动控制，先把现有产物变成软件界面。

必须实现：

1. Runs 列表
2. Run Detail Overview
3. Chunks 表格
4. QC 面板
5. Keyframes 画廊
6. Transcript viewer
7. Markdown preview

P0 可读取现有样本：

- `runs/stream-live_20260601_医疗行业AI转型一应用-20260601-225014.manifest.json`
- `runs/stream-live_20260601_医疗行业AI转型一应用-20260601-225004.gemini35.final-qc.json`
- `runs/stream-live_20260601_医疗行业AI转型一应用-20260601-225004.qwen-full.final-qc.json`
- `Markdowns/TTS_stream-live_20260601_医疗行业AI转型一应用-gemini35.md`
- `Markdowns/TTS_stream-live_20260601_医疗行业AI转型一应用-qwen-full.md`

验收标准：

- 用户不用打开文件夹也能看懂一次运行是否完整。
- 用户能从最终 QC 反查到 chunks、frames、transcript 和 Markdown。
- 用户能明确看到 Gemini/Qwen 的 provider、模型、窗口策略和 warnings。
- 页面能显示 2026-06-01 直播运行的完整链路。

## 8. P1 范围

P1 接入任务创建与启动控制：

- MP4 导入
- 回放 URL 探测
- 直播 URL dry-run
- 登录态检查
- 启动 `START_LIVE.bat` 或 Python CLI
- 实时 tail log
- 运行中增量刷新 chunks

P1 必须避免的坑：

- 不要让前端默认触发 Gemini/Qwen 真实调用。
- 所有模型调用按钮必须显示 provider、模型、预计调用次数、frame cap。
- 不要把 live/replay/local 三条路径写成三套互不兼容 UI。

## 9. P2 范围

P2 做工作流编排和对比：

- Gemini vs Qwen Markdown 对比
- one-shot vs sliding-window 对比
- 重跑 final synthesis
- 补抽 slides
- 按 warnings 推荐下一步动作
- 产物版本管理
- Run 导出报告

## 10. 前端技术建议

建议从本地 Web App 做起：

- React + Vite + TypeScript
- Tailwind 或现有轻量 CSS
- 后端 FastAPI 或 Flask
- 本地文件通过 API 读取，不让浏览器直接碰文件系统

理由：

- 当前系统是本地/Windows runner 场景，不适合一开始做云端 SaaS。
- React/Vite 足够快，适合做复杂工作台。
- FastAPI/Flask 可以直接复用 Python 文件解析逻辑。

如果需要更快 P0，可以先用 Flask/Jinja 做只读 dashboard，但后续交互会受限。

## 11. 明天实施顺序

1. 建 `frontend/` 和 `web_api/` 或 `app/` 基础结构。
2. 先写本地 artifact indexer，扫描 runs/Markdowns/Slides。
3. 用 2026-06-01 live run 做固定样本。
4. 实现 Runs 列表。
5. 实现 Run Detail 的 Overview/QC/Markdown。
6. 再加 Chunks/Transcript/Keyframes。
7. 最后考虑启动控制，不先碰真实执行。

## 12. 关键风险

- 文件命名规则历史上多次变化，前端不能硬编码单一模式。
- 同 base 多次运行可能混合 chunks，需要 run identity 或更强索引策略。
- 直播入口 BAT 仍有历史回退风险，前端启动控制前必须先稳定操作面。
- 真实模型调用成本高，前端按钮必须强制确认预算。
- 关键帧图片数量可能很大，画廊必须虚拟滚动或分页。

## 13. 一句话产品定义

zhihu 前端不是“视频转 Markdown 按钮”，而是一个本地多源视频/直播处理控制台：从输入、采集、转写、关键帧、QC 到最终 Markdown，全链路可见、可追踪、可恢复。
