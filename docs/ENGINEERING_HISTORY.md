# 研发日志总账

Date: 2026-05-17

本文档用于记录历史上每一次重要功能演进、架构修改、关键取舍、分支路线和后续规划。

它不是运行日报，也不是原始聊天记录；它只沉淀对项目后续研发有长期价值的决策事实。

## 记录原则

1. 每次新增功能、修改架构、拆分分支、改变处理流程，都要新增一条记录。
2. 每条记录必须说明背景、决策、原因、影响范围、验证情况和后续路线。
3. 不把一次运行失败简单写成架构结论；运行异常先进入 `docs/RUN_LOG.md` 或 `runs/*.md`，稳定结论再沉淀到本文档。
4. 代码提交、分支名、验证报告要尽量给出可追溯引用。
5. 结论可以标注状态：`planned`、`experimental`、`validated`、`production`、`deprecated`。

## 与其他文件的关系

| 文件 | 用途 |
|---|---|
| `docs/ENGINEERING_HISTORY.md` | 研发演进和架构决策总账 |
| `docs/RUN_LOG.md` | 每日运行、异常处理、代码修改前后效果对比 |
| `docs/BRANCH_USAGE.md` | 当前分支用途和 Windows/Mac 拉取方式 |
| `docs/WHISPER_BACKEND_IMPROVEMENT_PLAN.md` | whisper.cpp 后端专项方案 |
| `docs/WINDOWS_RUNBOOK.md` | Windows 执行手册 |
| `runs/*.md` | 运行和验证证据 |

## 记录模板

```md
## YYYY-MM-DD 标题

状态：

### 背景

-

### 决策

-

### 为什么这样做

-

### 影响范围

- 代码：
- 文档：
- 分支：
- 运行流程：
- 输出物：

### 验证情况

- 验证命令：
- 验证结果：
- 相关报告：

### 风险和取舍

-

### 后续路线

-
```

## 2026-05-07 批处理、断点续跑和长任务可观测性

状态：validated

### 背景

- 初始流程偏单视频处理，长批次运行时缺少稳定的进度恢复、日志观察和失败定位能力。
- Gemini Files API、文件上传、中文文件名、配额限制、视频分片等问题在多轮运行中集中暴露。

### 决策

- 将处理流程改为面向批量视频的可恢复流程。
- 使用 `.progress.json` 记录机器可读进度。
- 使用 `runs/*.md` 记录人可读运行报告。
- 对拆分视频按源视频聚合，避免每个 part 生成分散输出。

### 为什么这样做

- 长视频和批量视频运行时间长，必须能中断后继续。
- 单纯依赖终端输出无法支持跨机器协作和异常复盘。
- 按源视频输出 Markdown 更符合最终产品使用方式。

### 影响范围

- 代码：`zhihuTTS.py`
- 运行流程：批量扫描、断点续跑、重试、配额记录
- 输出物：`Markdowns/*.md`、`.progress.json`、`runs/*.md`

### 验证情况

- 多轮运行验证了断点续跑和配额限制行为。
- 发现免费层 Gemini 请求数是主要瓶颈，单纯缩小分片不能解决每日请求上限。

### 风险和取舍

- `.progress.json` 是机器状态文件，但需要跨机器协同，因此属于共享进度。
- 原始日志不适合长期共享，后续改为摘要进入 `runs/*.md` 和 `docs/RUN_LOG.md`。

### 后续路线

- 继续减少重复预处理。
- 缓存转写、关键帧和 Gemini payload。
- 分离运行证据和研发决策。

## 2026-05-08 上传模式兼容与早期稳定性修复

状态：validated

### 背景

- 初始批处理方向确定后，实际运行暴露出 Gemini SDK 调用方式、上传模式、空响应、文件名和长请求超时问题。
- 当时仍在探索 Files API、base64、file URI 等不同输入路径。

### 决策

- 增加 `UPLOAD_MODE`，便于在 base64、file URI、Files API 等路径间试错。
- 使用 SDK 提供的 `types.Part` 结构，减少 raw dict 兼容风险。
- 对空 `response.text` 和长时间 `generate_content` 增加保护。
- 增加数字排序、preflight、quote-safe、last-part-sleep 和 `RESOURCE_EXHAUSTED` 处理。

### 为什么这样做

- 早期阶段需要快速定位是上传路径问题、SDK 结构问题、模型响应问题还是速率限制问题。
- 长视频处理链路长，任何一个无保护异常都会让整批任务中断。
- 分片顺序和文件名兼容直接影响最终 Markdown 的内容顺序和可提交性。

### 影响范围

- 代码：`zhihuTTS.py`
- 运行流程：上传模式选择、Gemini 调用、分片排序、异常处理
- 输出物：早期 Markdown 生成稳定性

### 验证情况

- 相关提交：`dc3831b`、`c40a1a9`、`c4892d4`、`45b7a8b`、`17f3ca4`、`9b985af`
- 后续运行继续推进，说明这些基础保护成为后续批处理的稳定性基础。

### 风险和取舍

- 多上传模式增加了代码复杂度。
- 后续验证表明 `file_uri` 路线不适合作为主路径，需要逐步收敛。

### 后续路线

- 删除无效输入路径。
- 保留真正可验证、可恢复、可协作的主流程。

## 2026-05-12 输出推进与无效 file_uri 路线收敛

状态：validated

### 背景

- A09-A17 仍需生成 Markdown 输出。
- 早期保留的 `file_uri` 路线在实际 Gemini 视频理解中价值有限。

### 决策

- 完成 A09-A17 的 Markdown 输出。
- 提升 `MAX_RETRIES`，增强批处理容错。
- 修正 GitHub 文件名兼容问题。
- 删除 `file_uri` 死代码，避免继续误导运行配置。

### 为什么这样做

- 项目目标是稳定产出 NotebookLM 可用 Markdown，而不是保留所有试验路线。
- 本地 file URI 不等于模型可访问媒体资源，继续保留会增加维护和排错成本。

### 影响范围

- 代码：`zhihuTTS.py`
- 输出物：A09-A17 Markdown
- 运行流程：重试策略、输出文件名兼容

### 验证情况

- 相关提交：`3295edd`、`684c75b`
- A09-A17 输出进入 Git。

### 风险和取舍

- 删除 `file_uri` 后，远程 URL/媒体流能力需要另起验证路线，不能混入主生产流。

### 后续路线

- 继续把主流程聚焦在可验证输入。
- 后续视频流能力单独拆分为实验分支。

## 2026-05-14 本地预处理架构替代直接视频上传

状态：validated

### 背景

- 直接上传长视频给 Gemini 容易受 Files API、文件大小、配额、超时和 provider 支持能力影响。
- 项目需要更可控的本地预处理和更稳定的最终 Markdown 质量。

### 决策

- 引入本地 ffmpeg 抽帧和 Whisper 音频转写。
- 将 Gemini 的职责收敛为“基于转写文本 + 关键帧做结构化总结”。
- 尝试硬件加速，但对不稳定的 D3D11VA 硬解及时回退。
- 建立双机协作文件、依赖文件和 pre-commit 初版。

### 为什么这样做

- 本地预处理可以减少对 Gemini 视频文件解析链路的依赖。
- 关键帧和逐字稿让输出质量更可控，也更适合后续缓存和复用。
- 硬件加速必须服务于稳定生产，不能为了速度牺牲可恢复性。

### 影响范围

- 代码：`zhihuTTS.py`、`zhihuTTS_video.py`
- 文档：`COLLABORATION.md`
- Hook：`githooks/pre-commit`
- 依赖：`requirements.txt`
- 输出物：`Markdowns/TTS_0514_*.md`

### 验证情况

- 相关提交：`768e0a2`、`fdf464c`、`ade17e4`、`248711c`、`ba9d436`、`6dc8142`
- CPU faster-whisper + Gemini 2.5 Flash 完成 10 个新视频。

### 风险和取舍

- 本地转写引入 CPU/GPU 环境依赖。
- D3D11VA 硬解不稳定，被移除。
- whisper-cpp-python binding 编译复杂，后续改为外部 CLI 方案。

### 后续路线

- 使用缓存降低重跑成本。
- 将硬件加速封装成可选后端，并保留 CPU fallback。

## 2026-05-15 Gemini 续写与 MAX_TOKENS 输出完整性修复

状态：validated

### 背景

- 长视频生成的 Markdown 可能触发 `FinishReason.MAX_TOKENS`。
- 截断会导致最终输出只有标题、章节不全或内容缺失。

### 决策

- 抽出 `_call_gemini_with_retry()`。
- 增加 MAX_TOKENS 续写上限保护。
- 后续重构为 Gemini chat session 续写，保留上下文继续生成。
- 对已失败或不完整的输出进行定点重跑验证。

### 为什么这样做

- 简单重试无法保证从截断处继续。
- 输出完整性是产品质量问题，必须作为主流程能力处理。

### 影响范围

- 代码：`zhihuTTS.py`
- 输出物：`Markdowns/TTS_0515_*.md`
- 运行流程：Gemini 调用、续写、重试、失败状态更新

### 验证情况

- 相关提交：`8f722e5`、`af310e2`、`b947fdc`
- `RAG_02` 重跑后生成约 45KB 完整输出。
- 5/16 的复盘显示当天处理的样本未复现 `MAX_TOKENS`。

### 风险和取舍

- 续写会增加 Gemini 请求次数，影响每日 quota。
- 需要在运行日志中记录续写次数和 finish reason，避免把“完整输出”误判成“一次请求成功”。

### 后续路线

- 继续优化 prompt 和上下文拼接。
- 将长视频输出完整性纳入每日运行复盘。

## 2026-05-16 whisper.cpp CLI 后端与缓存改造

状态：production

### 背景

- 150 分钟级长视频处理耗时主要受本地音频转写和 Gemini 调用限制影响。
- faster-whisper CPU 可用但速度有限。
- Windows 侧具备尝试 whisper.cpp Vulkan CLI 的环境条件。

### 决策

- 增加外部 `whisper.cpp` CLI 后端。
- 保留 faster-whisper CPU 作为可靠 fallback。
- 使用 `WHISPER_BACKEND=auto` 作为默认安全模式。
- 增加 `cache/transcripts`、`cache/keyframes`、`cache/payloads` 预处理缓存。
- 在进度中记录 `backend_used`、`fallback_reason`、`failed_stage`。

### 为什么这样做

- `whisper-cpp-python` 路线编译和运行风险更高，CLI 边界更清晰。
- 自动 fallback 可以让 Windows 生产流程优先尝试加速，但不因加速不可用而整体中断。
- 缓存可以避免重跑时重复转写和抽帧。

### 影响范围

- 代码：`zhihuTTS.py`、`zhihuTTS_video.py`
- 文档：`docs/WHISPER_BACKEND_IMPROVEMENT_PLAN.md`、`docs/WINDOWS_RUNBOOK.md`
- 运行流程：转写后端选择、缓存复用、失败阶段记录
- 输出物：运行报告中增加后端和 fallback 信息

### 验证情况

- Mac 侧提交：`ca840e9 perf: add whisper.cpp CLI backend`
- Windows 侧验证：`runs/windows-whispercpp-validation-20260516.md`
- 复盘报告：`runs/windows-code-upgrade-retro-20260516.md`

### 风险和取舍

- GPU/CLI 路径依赖 Windows 本机配置，不作为硬编码项目配置提交。
- `auto` 模式提升稳定性，但性能验证需要区分 CPU fallback 和真实 Vulkan 后端。
- 运行效率提升不能只看单次样本，需要同类视频对比。

### 后续路线

- 继续收集相同视频在 CPU 与 whisper.cpp 后端下的耗时对比。
- 在运行日志中记录修改前后效率和输出质量变化。

## 2026-05-17 本地逐字稿输出与视频流验证路线拆分

状态：planned

### 背景

- 完整视频逐字稿此前主要存在于中间过程，没有进入最终输出物。
- 用户需要最终 Markdown 能包含完整逐字稿，便于复查和二次使用。
- 同时开始探索直接从远程视频流或直播流准实时提取逐字稿，但这条路线改动范围更大。

### 决策

- 拆成两个分支推进：
  - `feature/local-transcript-appendix`
  - `feature/stream-transcript-validation`
- 本地视频逐字稿输出作为生产路线独立推进。
- 视频流处理作为新方案验证路线独立推进。

### 为什么这样做

- 本地 MP4 处理是当前生产流程，风险要可控。
- 视频流路线涉及 URL 鉴权、分片、准实时输出、后续英文逐字稿和中文翻译，改动面更大。
- 两条路线混在一个分支会导致 Windows 用户拉错代码，也会影响生产稳定性。

### 影响范围

- 分支：`feature/local-transcript-appendix`、`feature/stream-transcript-validation`
- 文档：`docs/BRANCH_USAGE.md`
- 本地视频路线：`zhihuTTS.py`
- 视频流路线：`zhihuTTS_stream.py`

### 验证情况

- 已形成分支使用说明：`docs/BRANCH_USAGE.md`
- 直接签名 MP4 URL 已验证可以被 `ffprobe` 和 stream runner 处理。
- 真正直播流尚未拿到，需要后续使用真实 HLS、DASH、FLV、RTMP、RTSP 或可转换输入验证。

### 风险和取舍

- 回放 MP4 URL 不等价于直播流。
- 直播流可能需要 Cookie、Authorization、Referer、Origin、User-Agent 等浏览器上下文。
- WebRTC 场景可能没有单一 ffmpeg 可读 URL，需要桥接方案。

### 后续路线

- 本地路线：合并完整逐字稿附录和历史 Markdown 补齐能力。
- 视频流路线：继续验证媒体流输入、鉴权头、分片转写和准实时输出。
- 后续扩展：英文原文逐字稿、实时中文翻译、英文原文 + 中文翻译双轨输出。

## 2026-05-17 共享状态和日志边界重整

状态：production

### 背景

- 项目同时由 Windows 和 Mac 协作。
- 历史上存在机器角色、工具记忆、运行日志、原始日志、本机遥测混杂的问题。
- 需要统一哪些内容进 Git，哪些内容保持本地。

### 决策

- 按文件用途划分共享边界，不按机器身份划分。
- 本机专属配置、私有权限、运行环境偏好、本机遥测、缓存和密钥不共享。
- 项目共识、协作规则、可复现运行报告、进度状态、最终输出，以及对端需要继续执行的内容进 Git。
- 新增运行日志总账和研发日志总账。

### 为什么这样做

- Windows 和 Mac 都可能运行、分析、验证、修改文档；按机器身份划分会逐渐失真。
- 按文件用途划分更稳定，也更适合 hook 自动检查。
- 运行事实和研发决策分开，便于后续追溯。

### 影响范围

- 文档：`docs/SHARED_STATE_POLICY.md`、`COLLABORATION.md`、`docs/RUN_LOG.md`、`docs/ENGINEERING_HISTORY.md`
- Hook：`githooks/pre-commit`
- Git 跟踪：移除原始日志和 OpenWolf 本机遥测文件

### 验证情况

- 共享策略提交：`ea77639 docs: define shared state policy`
- 检查项：`git diff --check`、`sh -n githooks/pre-commit`、`githooks/pre-commit`、GitNexus `detect_changes`

### 风险和取舍

- 原始日志不再进 Git，精确证据需要主动摘录到共享文档。
- `.wolf` 中项目共识可以共享，但本机遥测必须排除。

### 后续路线

- 后续每次功能演进和架构修改都追加到本文档。
- 每天生产运行、异常处理和代码修改前后效果对比追加到 `docs/RUN_LOG.md` 或对应 `runs/*.md`。
