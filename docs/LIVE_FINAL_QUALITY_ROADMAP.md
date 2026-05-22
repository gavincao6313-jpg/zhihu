# Live Final Quality Roadmap

> 实时直播流最终生成质量提升路线图
> 创建：2026-05-22
> 负责人：Mac（代码） / Windows（运行验证）

---

## 背景

A/B 测试（2026-05-22，commit `9b98b21`）结论：

| 路径 | Chunks | 输出字符 | 章节数 | Gemini 策略 |
|------|--------|---------|-------|------------|
| 实时直播流 | 157 | 32,530 | 14 | chunk 级 `_call_gemini_stream` |
| 回放 URL→MP4 | 185 | 82,376 | 5 | file pipeline（全局一次） |
| 本地 MP4 | 182 | 81,850 | 8 | file pipeline（全局一次） |

差距根因：**不是 Prompt 弱，而是输入组织方式和合成策略不同。**

改进路线不从换模型或堆 Prompt 入手，而是：

> 保输入完整 → 证据包整理 → 分层生成 → 统一 finalizer → 自动 QC

---

## 目标架构（终态）

```
Live Capture
  → chunks / payloads / transcript / manifest
  → live_input_qc()
  → evidence_pack_builder()
  → section_synthesis (Pass A → Pass B → Pass C)
  → shared_finalizer()
  → final.md
  → section-notes/*.md
  → evidence/*.json
  → final-qc.json
  → final-markdown-qc.json
```

---

## P0：Live Final QC（让产物可信）

**目标：** 不改 Gemini 合成逻辑，只让直播最终产物变成可审计产物。

**主路径保留：** `scripts/build_stream_markdown.py:212`（现有 one-shot synthesis 不动）

**新增流程：**

```
collect transcript/frames
  → live_final_qc()          ← 新增
  → quality_manifest.json    ← 新增
  → existing Gemini call     ← 不改
  → prepend_quality_header() ← 新增（deterministic 后处理）
  → write final markdown
```

---

### P0 任务清单

#### P0-1 · `live_final_qc()` 函数
- [x] 在 `scripts/build_stream_markdown.py` 中新增 `live_final_qc(run_dir, base)` 函数
- [ ] 计算并返回以下指标：
  - `captured_duration_s`：合并逐字稿最后时间戳
  - `chunk_count`：正常 chunk 数
  - `transcript_chars`：合并逐字稿总字符数
  - `frame_count`：关键帧数量
  - `gap_count` / `gap_seconds`：缺口数和累计时长
  - `silent_chunk_count`：静音/无效 chunk 数
  - `failed_chunk_count`：转写失败 chunk 数
  - `first_timestamp_s` / `last_timestamp_s`：时间范围
  - `source_status`：`full` / `partial` / `interrupted`
- [ ] `source_status` 判定规则：
  - `failed_chunk_count > 0` 或 `gap_seconds > 60` → `partial`
  - 录制异常中断 → `interrupted`
  - 否则 → `full`
- **验证：** ✅ step1-verify 历史 run 验证通过，所有字段合理

#### P0-2 · `final-qc.json` 输出
- [x] Gemini 调用前生成并保存 `runs/stream-<base>-<run-ts>.final-qc.json`
- [ ] 字段结构：

```json
{
  "base": "...",
  "run_ts": "...",
  "source_type": "live",
  "source_status": "full",
  "chunk_count": 157,
  "transcript_chars": 123456,
  "frame_count": 812,
  "first_timestamp_s": 0,
  "last_timestamp_s": 9440,
  "timeline_duration_s": 9440,
  "gap_count": 0,
  "gap_seconds": 0,
  "silent_chunk_count": 0,
  "failed_chunk_count": 0,
  "synthesis_model": "gemini-2.5-pro",
  "synthesis_pass": "one-shot",
  "warnings": []
}
```

- [ ] `synthesis_model` 从实际调用参数读取，`synthesis_pass` 固定为 `"one-shot"`（P1 后改为 `"sectioned/3-pass"`）
- **验证：** ✅ JSON 可 parse，字段无 null，step1-verify 验证通过

#### P0-3 · Markdown 头部质量块（deterministic 注入）
- [x] 新增 `prepend_quality_header(gemini_text, manifest)` 函数，在 Gemini 返回后、落盘前执行
- [ ] `full` 状态头部格式：

```markdown
> **Live Final QC**
> - 输入类型: live
> - 采集状态: full
> - 覆盖时间: 00:00:00 – 02:37:20
> - chunks: 157 | gaps: 0 | transcript: 123,456 字 | frames: 812
```

- [ ] `partial` / `interrupted` 状态追加警告行：

```markdown
> - ⚠️ 采集状态: partial — 当前文档仅覆盖已采集片段，不代表完整直播内容。
> - 已知缺口: 01:22:10 – 01:24:35（145s）
```

- [ ] 头部由代码写入，Prompt 不包含任何元数据指令
- **验证：** ✅ header blockquote 正确生成，与 Gemini 正文分隔

#### P0-4 · 尾部覆盖 QC
- [x] 在 `live_final_qc()` 中加入尾部覆盖检查：
  - 若 `last_timestamp_s < timeline_duration_s × 0.85`，写入 `warnings`：`"tail_coverage_low: last={last_timestamp_s}s, expected≥{threshold}s"`
- [ ] 这个 warning 同时注入 Markdown 头部
- **验证：** ✅ step1-verify 无缺口无告警；时间戳格式 `[HH:MM:SS - HH:MM:SS]` 已适配

---

## P1：Sectioned Synthesis（分层生成，正文质量核心）

**目标：** 把 one-shot 改成三阶段分层合成，彻底解决长直播中后段被稀释的问题。

**模型策略：**

| Pass | 默认模型 | 升级条件 |
|------|---------|---------|
| Pass A · section notes | gemini-2.5-flash | 单段 QC 失败可切 pro 重跑 |
| Pass B · outline merge | gemini-2.5-flash | outline QC 弱时切 pro |
| Pass C · final doc | 可配置，推荐 gemini-2.5-pro | — |

---

### P1 任务清单

#### P1-1 · 输出目录结构

- [x] 新建 `runs/live-final/<base>-<run-ts>/` 作为 P1 运行根目录
- [ ] 子目录：

```
runs/live-final/<base>-<run-ts>/
  manifest.json          ← 总控文件，含所有 section 状态
  final-qc.json          ← 继承自 P0，加 synthesis_pass: sectioned/3-pass
  evidence/
    section_001.json
    section_002.json
    ...
  notes/
    section_001.md
    section_002.md
    ...
  outline.json
  final.md
  final-markdown-qc.json
```

- [x] 更新 `anatomy.md`
- **验证：** ✅ smoke test PASSED — 目录、manifest init/load/update/stale 全部验证通过

#### P1-2 · 分段策略（evidence builder）

- [ ] 新增 `evidence_pack_builder(transcript, frames, gaps, config)` 函数
- [ ] 分段规则（按优先级）：
  1. gap 处强制断段，gap 信息写入 section metadata
  2. 固定时间窗 `section_window_s = 600`（10 分钟）
  3. 末尾短段（`< min_section_s = 180`）合并到前一段
- [ ] 每个 section evidence 结构：

```json
{
  "section_id": "section_001",
  "start_s": 0,
  "end_s": 600,
  "transcript": "...",
  "frames": [
    {"ts": 35, "type": "unknown", "path": "..."},
    {"ts": 81, "type": "unknown", "path": "..."}
  ],
  "gaps": [],
  "chunk_ids": [1, 2, 3]
}
```

- [ ] `type` 字段 P1 阶段统一写 `"unknown"`，P2 再做分类
- **验证：** 用历史 step2 run 跑分段，检查各段时长分布、gap 是否正确切断

#### P1-3 · Section 状态管理（manifest.json）

- [ ] `manifest.json` 作为总控，每个 section 记录：

```json
{
  "section_id": "section_008",
  "start_s": 4200,
  "end_s": 4800,
  "evidence_hash": "sha256:...",
  "evidence_status": "done",
  "note_status": "pending",
  "note_model": null,
  "note_attempts": 0,
  "note_path": null,
  "last_error": null
}
```

- [ ] `note_status` 状态：`pending` / `running` / `done` / `failed` / `stale`
- [ ] `evidence_hash` 变更时，已完成的 note 标记为 `stale`
- [ ] 断点恢复规则：
  - `done` + hash 未变 → 跳过
  - `stale` / `failed` / `pending` → 重跑
  - Pass B/C：任意 section note 更新后重跑
- **验证：** 手动将某 section 的 `note_status` 改为 `pending`，重跑只处理该段

#### P1-4 · Pass A：Section Notes（gemini-2.5-flash）

- [ ] 新增 `run_pass_a(section_id, evidence, config)` 函数
- [ ] 每个 section 独立调用 Gemini，生成固定结构 section note：

```markdown
## Section 01 [00:00:00 – 00:10:00]
- 核心主题：
- 关键论点：
- 关键术语：
- 视觉证据：
- 重要案例：
- 原话候选：
- 行动项/作业：
- 不确定点：
```

- [ ] 默认 `gemini-2.5-flash`，`failed` 后最多重试 1 次；`note_attempts ≥ 2` 且仍失败，可选升级 pro
- [ ] 写入 `notes/section_NNN.md`，更新 manifest `note_status → done`
- [ ] 遵守 flash RPM 限制（10 RPM），相邻调用加 `sleep(6)`
- **验证：** 选 3 个历史 section 跑 Pass A，section note 结构完整，时间戳对应

#### P1-5 · Pass B：Outline Merge

- [ ] 新增 `run_pass_b(section_notes, config)` 函数
- [ ] 把所有 section note 输入 Gemini，生成全局章节树：

```json
{
  "chapters": [
    {
      "title": "错题本工作流构建",
      "start_s": 1760,
      "end_s": 3450,
      "sections": ["section_003", "section_004", "section_005"]
    }
  ]
}
```

- [ ] 默认 flash，outline QC 失败（章节合并不合理）时切 pro 重跑
- [ ] 输出写 `outline.json`
- **验证：** 章节数合理（2h 直播预期 8-12 章），无跨 section 时间顺序错误

#### P1-6 · Pass C：Final Document

- [ ] 新增 `run_pass_c(outline, section_notes, config)` 函数
- [ ] 输入：全局章节树 + 所有 section notes + 精选逐字稿片段 + 精选关键帧摘要
- [ ] 默认 pro（可配置），沿用现有 `utils.call_gemini()` 续写机制
- [ ] 输出写 `final.md`，文档 schema 见下方「统一文档规范」
- **验证：** Pass C 输出 final.md，结构完整，续写接缝格式无断裂

#### P1-7 · Final Markdown QC

- [ ] 新增 `final_markdown_qc(final_md_path, manifest, qc_manifest)` 函数
- [ ] QC 检查项：

| 检查 | 门槛 |
|------|------|
| H1 存在 | 必须 |
| 必要章节存在（元数据、知识字典、内容解析、行动项） | 必须 |
| 最后章节结束时间 ≥ last_section end × 0.9 | 必须 |
| markdown fence 闭合 | 必须 |
| heading 层级合法（无跳级） | 必须 |
| 无续写接缝重复段落 | 必须 |
| source_status 已注入 | 必须 |
| 中后段覆盖（最后 20 分钟在正文出现） | 警告 |

- [ ] QC 结果写 `final-markdown-qc.json`，含 `pass: true/false` 和 `issues[]`
- [ ] QC 失败处理（初版）：
  1. 格式问题 → 本地 deterministic 修复（fence 闭合、heading 修正）
  2. 覆盖问题 → 将缺失 section note 注入修复 prompt 重跑 Pass C
  3. 多次失败 → 标记 `pass: false`，保留产物，不阻塞流程
- **验证：** 故意破坏 final.md（删 H1、断 fence），QC 能检测并报告

#### P1-8 · Section Notes 作为 Sidecar 输出

- [x] `notes/section_NNN.md` 作为独立可用文件（不只是中间缓存）
- [x] `Markdowns/` 最终产物目录结构：

```
Markdowns/
  TTS_stream-<base>.md            ← 阅读版（原有位置）
  TTS_stream-<base>-sections/
    section_001.md
    section_002.md
    ...                           ← NotebookLM 检索版
```

- [x] 在 P0 头部 QC block 中注明两种 NotebookLM 使用模式
- **验证：** 上传 section-notes/ 目录到 NotebookLM，确认可检索

---

## P2：Frame & Visual Optimization（视觉证据优化）

**目标：** 让 Gemini 看到的是高价值视觉证据，而不是冗余噪声帧。

**依赖：** P1 完成并稳定后进行。P2 需要 P1 的 evidence builder 已经就位。

---

### P2 任务清单

#### P2-1 · 帧分类

- [x] 新增帧分类器，对每帧打 `type` 标签：
  - `slide`：PPT/幻灯片页面
  - `annotation`：有手写标注/高亮的帧
  - `demo`：代码、UI、演示界面变化
  - `speaker`：纯讲师画面（无屏幕内容）
  - `transition`：切换过渡帧
- [x] 更新 P1 evidence 里的 `type` 字段（从 `unknown` 变为实际分类）
- **验证：** 随机抽取 50 帧，人工核查分类准确率 ≥ 80%

#### P2-2 · 帧去重与优先级筛选

- [x] 相邻帧相似度检测（perceptual hash 或 SSIM），相似度 > 0.95 去重
- [x] 同一 PPT 页面多帧只保留最清晰 1 帧
- [x] 优先级规则：

| 帧类型 | 策略 |
|--------|------|
| slide 切换帧 | 高优先级保留 |
| annotation 前后帧 | 高优先级保留 |
| demo/代码/UI 变化帧 | 保留 |
| 同页 PPT 重复帧 | 去重，保留 1 帧 |
| speaker 画面 | 每 5 分钟最多保留 1 帧 |

- **验证：** 2h 直播帧从 800+ 压缩到 200 以内，高价值帧无损失

#### P2-3 · Slide-Aware Section Boundary

- [x] 检测幻灯片切换密集区（`slide` 帧密度骤增位置）
- [x] 在 P1 分段规则中增加优先级 1.5（gap 之后，固定窗之前）：幻灯片切换密集区作为软边界
- **验证：** 分段边界与演讲主题切换点对齐度优于纯固定窗

#### P2-4 · Cleaned Transcript

- [x] 对 raw transcript 做后处理：
  - 去除重复词（ASR 常见抖动）
  - 可选过滤停顿词（"那个"、"就是"、"嗯"）
  - 保留时间戳锚点
- [x] `cleaned_transcript` 作为单独 sidecar 保存（不替换 raw）
- [x] Pass A 输入优先用 cleaned，raw 作为审计保留
- **验证：** cleaned transcript 对照 raw，字符减少 5-15%，内容无丢失

#### P2-5 · 术语归一化

- [x] 维护项目级术语表 `scripts/terminology.json`：
  - 通用：Cursor、Claude Code、MiniMax Agent、RAG、MCP、CLI、API
  - 直播场景特有：错题本、教师 Agent 等可配置追加
- [x] 在 evidence builder 阶段对 transcript 做归一化替换
- **验证：** 历史 transcript 中术语漂移归一化后消失

#### P2-6 · 同视频三路对照评测

- [ ] 对同一场直播素材，用相同维度对比三路结果：
  - 直播流（P1 sectioned synthesis）
  - 回放 URL（file pipeline）
  - 本地 MP4（file pipeline）
- [ ] 评测维度（①②③ 读 final-markdown-qc.json，④ 人工，⑤ grep）：
  - ① 正文字符数（不含逐字稿附录）
  - ② 最后章节时间戳覆盖率
  - ③ 尾部 20 分钟是否覆盖
  - ④ 关键知识点命中率（人工抽查 10 点）
  - ⑤ 视觉证据引用数（`grep -c "!\[" final.md`）
- **验证：** 直播流 P1 正文质量与回放/本地 MP4 差距 < 20%
- **触发条件：** 下次直播结束 → 跑完三路 pipeline → 三份 final.md 产出后执行

---

## 统一文档规范（三路共用 finalizer schema）

> P1 Pass C 和现有 file pipeline finalizer 最终输出同一结构

```markdown
# <直播标题>

> **Live Final QC**
> - 输入类型: live / replay / local
> - 采集状态: full / partial / interrupted
> - 覆盖时间: HH:MM:SS – HH:MM:SS
> - chunks: N | gaps: N | transcript: N 字 | frames: N
> - 合成模型: gemini-2.5-pro | synthesis_pass: sectioned/3-pass

## 0. 生成元数据
## 1. 视频元数据
## 2. 核心知识字典
## 3. 详尽内容解析
## 4. 遗留问题与下一步行动
## 附录 A：检索版逐字稿（cleaned）
```

> raw transcript 单独保存为 sidecar，不进入正文。

---

## 逐字稿产物规范

| 产物 | 位置 | 用途 |
|------|------|------|
| raw transcript | `runs/.../stream-<base>.combined-transcript.txt` | 审计、重跑 |
| cleaned transcript | `runs/.../stream-<base>.cleaned-transcript.txt` | NotebookLM 上传 |
| final body | `Markdowns/TTS_stream-<base>.md` | 知识文档正文 |

---

## 不做的事

| 方向 | 原因 |
|------|------|
| 直播采集中做重 Gemini 合成 | 采集优先级高于总结；实时合成质量已验证不足 |
| 只扩大 Prompt | Prompt 已足够重，问题在输入组织和合成策略 |
| 单独用字符数评估质量 | 逐字稿附录会放大字数；质量需拆成覆盖率、视觉证据等维度 |

---

## 当前进度

| 任务 | 状态 |
|------|------|
| P0-1 `live_final_qc()` | ✅ 完成 2026-05-22 |
| P0-2 `final-qc.json` 输出 | ✅ 完成 2026-05-22 |
| P0-3 Markdown 头部注入 | ✅ 完成 2026-05-22 |
| P0-4 尾部覆盖 QC | ✅ 完成 2026-05-22 |
| P1-1 输出目录结构 | ✅ 完成 2026-05-22 |
| P1-2 evidence builder | ✅ 完成 2026-05-22 |
| P1-3 section 状态管理 | ✅ 完成 2026-05-22 |
| P1-4 Pass A section notes | ✅ 完成 2026-05-22 |
| P1-5 Pass B outline merge | ✅ 完成 2026-05-22 |
| P1-6 Pass C final doc | ✅ 完成 2026-05-22 |
| P1-7 Final Markdown QC | ✅ 完成 2026-05-22 |
| P1-8 section notes sidecar | ✅ 完成 2026-05-22 |
| P2-1 帧分类 | ✅ 完成 2026-05-22 |
| P2-2 帧去重与优先级 | ✅ 完成 2026-05-22 |
| P2-3 slide-aware boundary | ✅ 完成 2026-05-22 |
| P2-4 cleaned transcript | ✅ 完成 2026-05-22 |
| P2-5 术语归一化 | ✅ 完成 2026-05-22 |
| P2-6 三路对照评测 | ⏳ 待验证（需下次直播产出三路 final.md 后人工比对） |

---

## 2026-05-22 真实直播复盘（105 chunks / 1h45m）

### 结论

| 环节 | 判断 |
|------|------|
| 实时采集 | ✅ 合格（105 chunks, 0 gaps, 0 failed） |
| chunk 连续性 | ✅ 合格 |
| transcript 合并 | ✅ 修复后合格（bug-058 已修） |
| frame 输入 | ✅ 合格（335 frames） |
| P0 final-qc.json | ✅ 有效，证明源可审计 |
| one-shot 最终正文 | ⚠️ 可用，但尾段覆盖不足（最后章节 01:14，transcript 到 01:45） |
| P1 sectioned live 方案 | ❌ 当前不可进生产（违反 Gemini 配额约束） |

### Findings 与对应动作

| Finding | 级别 | 状态 |
|---------|------|------|
| P1 --sectioned 仍可达生产路径 | High | ✅ main BAT/build_stream_markdown.py 已无 --sectioned（ad2deb1 revert） |
| 最终 Markdown 正文尾段压缩（最后 30min 未进章节） | High | ✅ 新增 `check_markdown_body_coverage()` 自动检测 gap>120s 时 warn |
| chunk 分组逻辑错误（105 chunks → 105 groups → 1 chunk） | High | ⚠️ 临时修复（bug-058）：--run-ts 未指定时用全部 chunk；run identity 正确设计待做 |
| utils.py 缺失（feature 分支 cherry-pick 漏带依赖） | High | ✅ WIN 43f43f5 已补；cerebrum 已记录规则 |
| merge_stream_chunks.py SyntaxWarning | Medium | ✅ bug-059 已修 |

### 待落地（P0.1）

- [ ] **run identity 重设计**：用 capture manifest session_ts 作为主键，chunk 记录所属 run_id，finalizer 从 manifest 选 chunk，不再依赖文件名 timestamp
- [ ] **P0.2 验证**：用今晚 105-chunk transcript 重跑，确认章节覆盖到 01:45:00 或 warn 正确触发

### 不走的路

| 方向 | 原因 |
|------|------|
| P1 live sectioned（每 section 一次 Gemini） | 180min 直播 ≥20 次调用，打满 Free-tier RPD |
| 提升质量靠加 Gemini 请求数 | 配额约束优先；应走输入前处理 + tail emphasis + coverage QC |
