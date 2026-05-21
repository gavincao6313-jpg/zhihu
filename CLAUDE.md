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
