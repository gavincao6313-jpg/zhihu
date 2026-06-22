# OpenWolf

@.wolf/OPENWOLF.md

This project uses OpenWolf for context management. Read and follow .wolf/OPENWOLF.md every session. Check .wolf/cerebrum.md before generating code. Check .wolf/anatomy.md before reading files.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **zhihu** (32978 symbols, 35561 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

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

Free-tier limits — verified from AI Studio rate-limit page on 2026-06-17
(screenshot evidence). Official docs no longer print fixed free-tier RPD;
AI Studio `rate-limit` is the source of truth. RPD is **per-model** (each
model has its own independent daily budget). The earlier "250 RPD" figures
below were stale and misled analysis for two rounds — do NOT trust them.

| Model | RPM | TPM | RPD (verified) |
|---|---:|---:|---:|
| `gemini-3.5-flash` | 5 | 250,000 | **20** |
| `gemini-2.5-flash` | 5 | 250,000 | **20** |
| `gemini-3-flash` / API id 待 smoke test | 5 | 250,000 | **20** |
| `gemini-2.5-flash-lite` | 10 | 250,000 | **20** |
| `gemini-2.5-pro` | 5 | 250,000 | 100 (not re-verified) |

Key consequences:
- `DEFAULT_DAILY_LIMIT_GEMINI = 18` in `batch_process_external.py` is the
  PER-MODEL daily cap (real RPD is 20; the picker reserves each video's
  expected calls so a model never exceeds it). Do NOT set it to 20+ (429).
- RPD is per-model, so the free way to scale throughput is round-robin across
  several free flash models (`GEMINI_MODEL_POOL`). Default pool = 3 verified
  models (gemini-3.5-flash / gemini-2.5-flash / gemini-2.5-flash-lite),
  about 54/day. `gemini-3-flash` is EXCLUDED from the default pool until its
  real API model id (likely `gemini-3-flash-preview`) and RPD pass a live smoke test.
  NOT paid Qwen/DashScope.
- TPM 250k is still the binding per-call ceiling (see GEMINI_MAX_FRAMES guard).

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


## 变更分级控制

代码变更在动手前必须先定级。文档和运行产物，如果不影响执行流程或协作约定，默认按低风险处理。

| 级别 | 范围 | 最低验证要求 |
|------|------|-------------|
| L1 | 注释、文案、配置值、纯样式、不影响执行的文档 | `python -m py_compile <file>` 语法检查 |
| L2 | 新增函数、修改业务逻辑、新脚本或新 CLI 参数 | `ruff check <file>` 或 `python -m pyflakes <file>` + 相关脚本冒烟测试 |
| L3 | 跨模块重构、共享路径改动、命中下方任一高风险区域 | 核心链路端到端运行 + 回归冒烟检查 |

**高风险区域 —— 以下任意改动至少归为核心 L2，必须进行外部 AI 审查：**

- Gemini 调用次数、重试、续写、配额预算逻辑
- 流录制、切片、恢复、checkpoint、manifest 生成
- 共享转写路径（`zhihuTTS_video.py` transcribe 相关函数）
- 跨平台 BAT/SH 运行入口
- 文件删除、清理、覆盖行为
- 长任务状态恢复逻辑
- 并发、超时、异常恢复逻辑
- 核心文件：`zhihuTTS_stream.py`、`zhihuTTS_video.py`、`zhihuTTS.py`

**L2/L3 的 symbol 改动仍须遵守上方 GitNexus 规则。** 外部 AI 审查不能替代 impact analysis 和 `gitnexus_detect_changes()`。

**L3 及核心 L2 变更在合并前必须经过外部 AI 独立审查。** 具体流程见 `.claude/rules/review.md`（diff 生成、审查包格式、Auditor prompt、对质步骤）。

## AI 副驾驶行为约束

- 不得带着已知失败的必跑检查交付。如果某项检查无法运行，必须明确说明原因和风险，不得描述为"可忽略"。
- 不得借局部需求顺手重构周围稳定代码。如需重构，必须先向用户申请提升至 L3 流程。
- 只在外部输入边界做校验：CLI 参数、文件输入、API 返回、跨模块不可信数据。只在能恢复或能补充诊断的地方捕获异常，禁止用宽泛异常捕获掩盖程序错误。
