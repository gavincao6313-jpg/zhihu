# OpenWolf

@.wolf/OPENWOLF.md

This project uses OpenWolf for context management. Read and follow .wolf/OPENWOLF.md every session. Check .wolf/cerebrum.md before generating code. Check .wolf/anatomy.md before reading files.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **zhihu** (3745 symbols, 4122 relationships, 47 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/zhihu/context` | Codebase overview, check index freshness |
| `gitnexus://repo/zhihu/clusters` | All functional areas |
| `gitnexus://repo/zhihu/processes` | All execution flows |
| `gitnexus://repo/zhihu/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->

## Gemini API Free-Tier Limits

This project currently uses the Gemini API on the **Free** usage tier. Treat
Gemini API quota as a scarce project-level resource.

Official reference:
<https://ai.google.dev/gemini-api/docs/rate-limits>

Rules from the official Gemini API rate-limit documentation:

- Rate limits are evaluated across RPM, TPM, and RPD.
- RPM means requests per minute.
- TPM means input tokens per minute.
- RPD means requests per day.
- Limits are applied per Google Cloud / AI Studio project, not per API key.
- RPD resets at midnight Pacific Time.
- Active limits can change by account, model, and usage tier; check AI Studio
  when exact current limits matter.

Project default free-tier ceilings to design against unless AI Studio shows
stricter active limits:

| Model | RPM | TPM | RPD |
|---|---:|---:|---:|
| `gemini-2.5-pro` | 5 | 250,000 | 100 |
| `gemini-2.5-flash` | 10 | 250,000 | 250 |
| `gemini-3.5-flash` | 10 | 250,000 | 250 |

Project engineering constraints:

- All code changes that can call Gemini must explicitly account for RPM, TPM,
  and RPD before implementation.
- Prefer one Gemini synthesis call per video, replay, or live stream. Duplicate
  synthesis paths are a bug unless the user explicitly approves them.
- Do not add default-on Gemini calls in wrapper scripts, batch scripts, retries,
  validation tools, or model discovery utilities.
- Any retry or continuation logic must have a small explicit cap, must count
  toward request budget, and must honor 429 / `RESOURCE_EXHAUSTED` backoff.
- Do not blindly retry deterministic errors such as bad input, missing files,
  invalid model names, or empty transcript payloads.
- Large transcript + keyframe jobs must estimate or bound input size before
  calling Gemini. If the estimate may exceed `250,000` input TPM for the active
  minute, split, sample, postpone, or require explicit user approval.
- New CLI/BAT/SH flows should expose dry-run or budget controls before Gemini
  execution, such as max requests, max frames, max continuations, and no-Gemini
  modes.
- Never run `GeminiModelList.py` or other model-scanning scripts as part of a
  normal production workflow, because each model probe can consume real quota.


PR rules：
1. 核心定位与原则
本项为 一人公司 (OPC) 架构。为同时兼顾“单人极速吞吐”与“系统级稳定性”，拒绝传统团队的人肉 PR 审批流，全面推行 【自动化拦截 + 双 AI 对抗审查】 机制。
人类角色： 首席架构师 / 终审法官。负责拆解需求、判定方向、合并代码。
当前 AI (Driver)： 业务执行官。负责高强度代码输出、修复报错。
外部 AI (Auditor)：独立质检官。拥有完全隔离的上下文，负责无情挑刺。
2. 代码变更分级控制架构
任何代码变动，无论大小，必须根据下表严格分流执行：
变更级别,场景定义,本地硬性准入,审查机制,合并通路
L1：微小变更,改参数、换文案、补注释、纯样式微调,1. 本地 Lint 通过2. 本地编译无报错,免人工/免 AI 审查,允许直推 main
L2：功能迭代,新增页面、组件、业务接口、局部逻辑优化,1. 类型检查无报错2. 本地 build 成功,单兵自查 + 快速合并,切分支开发，通过后合并
L3：系统重构,核心底层、数据库、跨模块重构、大规模重写,1. 全量自动化检查通过2. 核心链路跑通,双 AI 对抗审查 (必须),切分支，对质闭环后合并
3. 双 AI 对抗审查流程 (Adversarial AI Review)
对于所有 L3 级重构（或涉及核心逻辑的 L2 变更），在合并入主干前，必须无条件执行以下“三步闭环法”：

阶段一：Driver 打包（当前实例执行）
当你（执行 AI）完成编码后，必须在本地处理完所有编译/类型错误。确认回归【零报错】状态后，生成当前分支相对于主干的干净 Diff 文件：
# 自动导出当前分支相对于主干的干净 Diff 文件
git diff main > ai_review_diff.patch

阶段二：Auditor 审判（人类调动外部独立 AI 执行）
人类（开发者）将 ai_review_diff.patch 拖入一个完全干净、无当前项目上下文的独立 AI 实例，并直接投喂以下【毒舌审计指令】：
🎯 外部 Auditor 专属指令：
“你现在是本项目的顶级首席架构师与安全专家。请对以下 Git Diff 进行极度严苛的代码审计。你必须表现得像一个挑剔、不留情面的高级顾问。
请仅针对以下 4 点输出一份精简、无废话的【毒舌审计报告】：
代码退化与意外改动： 执行者是否在改动目标之外，‘顺便’误改或重写了周围原本稳定的公共逻辑？是否有过度设计？
隐蔽边缘漏洞： 是否存在边缘 case 未处理（如 Null/Undefined 崩溃、异步竞态条件、未捕获的 Promise 报错、内存泄露、并发死锁）？
安全与性能隐患： 是否引入了潜在的 O(N^2) 循环、重复的 SQL/API 请求，或者硬编码的敏感信息？
代码污染： 是否残留了调试用的 console.log、print、未使用的变量或 AI 遗留的垃圾注释？
【以下为 Diff 数据】
[粘贴 ai_review_diff.patch 内容]”
阶段三：对质与闭环 (Reconciliation)
人类作为法官，快速浏览 Auditor 吐出的审计报告，过滤掉误报，提取有效漏洞。
将有效漏洞作为新任务反向派发给 Driver (当前 Claude 实例)：
“这是外部审计专家对你刚刚写的代码提出的质量质疑：[粘贴具体漏洞点]。请立即针对这些漏洞进行精准修复，不要引入新 Bug。”
Driver 修复完毕，本地重新通过 Lint 和 Type Check 后，人类方可执行合并。

4. 给 AI 副驾驶（Driver）的特别行为约束
当你作为我的副驾驶在本项目中编写代码时，请死守以下底线：
严禁带病交付： 任何时候，不要对我说“这个类型报错可以先忽略”。在交工给我之前，必须保证本地运行没有一处红线报错。
克制重构冲动： 严禁在修改一个局部参数或小功能时，擅自顺便重写周围原本稳定的老代码。如需重构，必须先向我申请提升至 L3 流程。
编写自防御代码： AI 极易遗忘边界。请在编写函数时，主动加上完备的入参校验（Null/Empty 检查）与异常捕获（Try-Catch），主动防御接下来的 Auditor 审计。