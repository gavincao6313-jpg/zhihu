# Qwen Long Video Optimization Plan

> Date: 2026-05-26
> Context: WIN completed same-live-source Gemini/Qwen A/B validation. Qwen3.6-Flash is reliable and cost-visible, but current one-shot path over-compresses long live videos and is limited to 250 input frames.

## Current Finding

For NotebookLM source documents, Gemini output is currently better because it preserves native context: exact prompts, code/config blocks, speaker wording, case details, scores, and long examples.

Qwen output is cleaner and more structured, especially in Glossary and outline generation, but it behaves like an executive-summary writer. It compresses or drops details that NotebookLM needs for later RAG retrieval, including:

- Coze repair prompts and code/prompt blocks.
- Concrete case scores and evaluation reasons.
- Long examples such as rewrite drafts and personal-experience stories.
- Detailed capability-model subitems.
- Speaker wording and original context needed for grounding.

The optimization goal is not to make Qwen "shorter and cleaner". The goal is to force Qwen into a NotebookLM source-document workflow:

```text
full transcript + all frames
  -> dynamic sliding-window faithful extraction
  -> structured window notes
  -> final assembly with strong glossary/index
  -> NotebookLM-ready Markdown
```

## Real-Run Finding After Sliding-Window Validation

WIN validated `TTS_stream-live-ab-20260526-qwen-qwen-sw.md` after the first Qwen sliding-window implementation. The result changes the strategy:

- Qwen sliding-window successfully fixes the 250-frame limit and long-tail forgetting problem.
  - The real run covered all `439/439` frames across 3 windows.
  - It preserved important prompts/code/config blocks much better than Qwen one-shot.
  - It restored late-stream details such as Coze context compression, Dreamina/即梦 cost examples, Remotion, and FDE discussion.
- Qwen still over-compresses final prose during the last assembly pass.
  - The final body improved from about 6.1k chars to about 10.6k chars, but QC still reported `qwen_overcompressed_body`.
  - Window note 001 preserved `75分`, but the final qwen-sw Markdown dropped it. This proves extraction worked and loss happened in final assembly.
  - The final qwen-sw timeline also produced overlapping chapters around `01:42 - 02:10`.
- Gemini remains the best single source body for NotebookLM because it preserves narrative context, case texture, and speaker wording more naturally.

Important correction: the Gemini evaluator's "best NotebookLM document" recommendation is useful for quality analysis, but it must not become the production engineering path. Calling two large models and then merging their outputs is not acceptable for the current cost/quota constraints. Gemini stays a benchmark/evaluator unless the project later upgrades to a paid Gemini API budget.

Therefore, the production-quality target remains a **single-provider Qwen workflow**:

```text
full transcript + all frames
  -> Qwen dynamic sliding-window faithful notes
  -> deterministic critical-fact extraction from Qwen notes
  -> Qwen final assembly with mandatory fact checklist and technical asset appendix
  -> NotebookLM-ready Markdown
```

In this architecture, Qwen sliding-window must produce the final user-facing document independently. Gemini output can be used only as an offline benchmark for analysis, not as a required production input.

## Progress Tracking Table

| ID | Item | Status | Notes |
|---|---|---|---|
| D1 | Qwen-specific faithful extraction prompt | Done | Window note prompt forbids executive-summary compression and requires prompt/code/config retention. |
| D2 | Qwen final assembly prompt | Done | Qwen-only assembly now receives critical facts and window notes. |
| D3 | Normalized NotebookLM document structure | Done | H1, metadata, Glossary, timestamped chapters, next actions. |
| D4 | Explicit `--synthesis-pass sliding-window` | Done | Qwen-only opt-in; Gemini rejected. |
| D5 | Dynamic Qwen windows under 250-frame cap | Done | Validated on 439-frame live source with 3 windows. |
| D6 | Window note persistence and resume | Done | Notes include source hash and metadata; `--resume-window-notes` supported. |
| D7 | Frame-policy reporting | Done | Global and per-window frame counts/types/overlap recorded. |
| D8 | Window coverage QC | Done | `qwen_window_coverage` marker and QC. |
| D9 | Critical facts checklist | Done | Extracts scores, dates, costs, tools, prompt keywords from window notes. |
| D10 | Qwen-only final assembly hardening | Done | Requires critical facts, technical asset appendix, and non-overlap timeline. |
| D11 | Qwen-only QC hardening | Done | Fact retention, timeline overlap, technical asset appendix checks. |
| D12 | End-to-end Qwen usage aggregation | Done | Separates `current_run_usage` and `end_to_end_usage`. |
| D13 | Long narrative retention | Done locally | Added Narrative Evidence Blocks, narrative retention QC, and deterministic narrative appendix fallback. Needs WIN real-output validation under U1. |
| D14 | Balanced frame quota tuning | Done locally | Frame sampling now keeps representative context frames instead of letting slide anchors consume the whole image cap. Needs WIN real-output validation under U1. |
| U1 | WIN real-output validation after P2 hardening | Not done | Need rerun with `--resume-window-notes` and inspect final QC. |
| U2 | Offline benchmark report | Not done | Optional comparison report only; must not become production dependency. |
| U3 | Comparative scoring | Not done | Detail retention, prompt preservation, case depth, visual coverage, NotebookLM readiness. |
| U4 | Human-review diff report | Not done | Highlight dropped prompts, numbers, long stories, and shortened examples. |

## Design Principles

1. **Faithful extraction before summarization.**
   Window passes must preserve evidence and wording. Final assembly may organize, but must not invent or over-compress.

2. **Let Qwen see all visual evidence across calls.**
   Qwen's single-call frame cap is 250, so long videos must use multiple bounded windows instead of dropping frames globally.

3. **Use Qwen's strengths deliberately.**
   Qwen is good at Chinese structure, glossary, and clean indexing. Use those strengths in final assembly, not in the first evidence-capture pass.

4. **Keep the default live path safe.**
   Do not make multi-call Qwen or Gemini workflows default-on in `run_zhihu_live.bat`. Qwen sliding-window synthesis must be explicit opt-in.

5. **NotebookLM is the target.**
   The source Markdown should favor retrieval depth over human skim speed. A longer, grounded document is better than a concise executive summary.

## P0: Prompt And Output Contract Fixes

- [x] Add a Qwen-specific faithful-extraction prompt for sliding-window notes.
  - Must explicitly forbid executive-summary compression.
  - Must require preserving original prompts, code/config blocks, UI labels, case scores, concrete numbers, and speaker wording.
  - Must require Markdown code blocks when the source contains prompts/config/code.
  - Must output window notes, not final article prose.

- [x] Add a Qwen final-assembly prompt.
  - In current one-shot mode, uses transcript + selected frames directly.
  - In future sliding-window mode, should use window notes as the only authoritative input.
  - Generates NotebookLM Markdown with H1, metadata, Glossary, detailed timeline chapters, next actions, full transcript appendix, and visual evidence index.
  - Allows Qwen to improve Glossary and headings, but forbids dropping evidence captured in window notes.

- [x] Normalize Qwen document structure to Gemini-quality requirements.
  - H1 title required.
  - `## 1. 视频元数据` required.
  - `## 2. 核心知识字典（Glossary）` required.
  - `## 3. 详尽内容解析` required.
  - Every timeline chapter must use `### [HH:MM:SS - HH:MM:SS] title`.
  - Every chapter must include `核心论点`, `详细展开`, `视觉/屏幕内容`, and `重要金句/原话`.

## P1: Dynamic Sliding Window For Qwen

- [x] Implement an explicit Qwen synthesis pass option.
  - Proposed CLI: `--provider qwen --synthesis-pass sliding-window`.
  - Keep current one-shot Qwen path available for cheap/fast runs.
  - Do not enable this automatically from `DASHSCOPE_API_KEY`.

- [x] Build dynamic windows from transcript + frames.
  - Each window targets 200-220 new frames.
  - Reserve 20-30 frames for overlap and boundary context.
  - Hard cap must never exceed `QWEN_IMAGE_HARD_LIMIT = 250`.
  - Slide/annotation dense regions should create shorter windows.
  - Low-visual-change speech regions can create longer transcript windows.

- [x] Preserve timeline continuity.
  - Include overlap frames and transcript on both sides of a boundary.
  - Mark overlap sections in window notes.
  - Final assembly must deduplicate overlap instead of losing context.

- [x] Persist intermediate window notes.
  - Suggested path: `runs/stream-{base}-{run_ts}.qwen-window-{NNN}.notes.md`.
  - Include source window start/end, frame counts, selected frame paths, transcript char count, model usage, and content hash.
  - Reuse existing notes on resume when source hash matches.
  - Current status: implemented with `--resume-window-notes`; each note stores source hash, model, frame counts, frame policy, usage, API calls, and finish reason.

## P1: Frame Selection Improvements

- [x] Replace global top-N frame sampling for Qwen sliding-window mode.
  - Current one-shot path selected 250/439 frames and dropped 189 frames.
  - Sliding-window mode should cover all 439 frames across multiple calls.

- [ ] Keep slide frames as anchors, but do not starve context frames.
  - Current priority sampling keeps slides and annotations first.
  - Add per-window quotas, for example:
    - all slide-change frames in window;
    - representative annotation frames;
    - at least a small context-frame budget when available.

- [x] Add frame-policy reporting per window and globally.
  - Total frames.
  - Frames covered by at least one window.
  - Frames dropped.
  - Slide/annotation/context counts.
  - Overlap count.

## P1: NotebookLM Quality Gates

- [x] Add deterministic QC for Qwen output.
  - H1 exists.
  - Timestamped chapter headings exist and reach stream tail.
  - Body character count is above configured threshold.
  - Required sections exist.
  - Code block count is nonzero when source window notes contain code/prompt blocks.
  - Prompt keywords such as `Prompt`, `提示词`, `所见即所得`, `不要替换` are preserved when present in source notes.

- [x] Add evidence retention checks.
  - Every window note must be referenced by final Markdown.
  - Each timeline chapter should cite at least one window or time range.
  - If a window contains code/prompt blocks, final Markdown must include or reference them.
  - Current status: final assembly prompt requires `<!-- qwen_window_coverage: ... -->`; QC warns with `qwen_window_unreferenced` if the marker is missing or omits windows. Per-chapter citation checks remain a future refinement.

- [x] Add QC warnings to final-qc JSON.
  - `qwen_overcompressed_body`
  - `qwen_missing_h1`
  - `qwen_missing_code_blocks`
  - `qwen_window_unreferenced`
  - `qwen_frame_coverage_low`

## Implementation Log

- 2026-05-26: P0 one-shot Qwen hardening started in `scripts/build_stream_markdown.py`.
  - Set `QWEN_IMAGE_HARD_LIMIT = 250`.
  - Added `QWEN_NOTEBOOKLM_PROMPT_TEXT` for Qwen final assembly / one-shot NotebookLM output.
  - Qwen provider now uses the Qwen-specific prompt instead of Gemini prompt.
  - Added `check_qwen_notebooklm_quality()` with H1, required sections, timestamped chapter, chapter field, body ratio, code block, and prompt-keyword checks.
  - Added `qwen_notebooklm_qc` metrics and Qwen warnings to final QC JSON.
  - Verified with `python3 -m py_compile` and offline dry-run/mock provider output.
- 2026-05-26: P1 Qwen sliding-window pipeline started in `scripts/build_stream_markdown.py`.
  - Added `--synthesis-pass one-shot|sliding-window`; sliding-window is Qwen-only and explicit opt-in.
  - Added dynamic frame windows with 200 target new frames and overlap bounded by the 250-frame hard cap.
  - Added per-window transcript slicing, overlap metadata, frame type counts, and `qwen_window_policy` in final QC.
  - Added Qwen window-note prompt, final assembly prompt, initial window note persistence, and final assembly from notes.
  - Verified `--provider qwen --synthesis-pass sliding-window --dry-run`; verified Gemini rejects `--synthesis-pass sliding-window`.
- 2026-05-26: P1 sliding-window resume/QC hardening.
  - Added `--resume-window-notes` for explicit reuse of matching window notes.
  - Added source hash over prompt contract, model, window transcript, frame timestamps/markers/paths, and frame file metadata.
  - Window notes now include JSON metadata: source hash, model, frame counts, frame policy, usage, API calls, and finish reason.
  - Final assembly prompt now requires hidden `qwen_window_coverage` marker; QC records `qwen_window_coverage_qc` and warns with `qwen_window_unreferenced` when coverage is missing.
  - Verified note hash read/write, resume flag validation, mock missing coverage warning, and mock coverage success.
- 2026-05-26: Windows live wrapper pass-through.
  - Added explicit `run_zhihu_live.bat --qwen-sliding-window` to pass `--synthesis-pass sliding-window`.
  - Added `run_zhihu_live.bat --resume-window-notes` to pass `--resume-window-notes`.
  - Kept default BAT behavior as one-shot; sliding-window remains explicit opt-in and Qwen-only.
  - Updated dry-run, worker logs, finalizer command, and manual fallback commands to include synthesis-pass and resume-window-notes state.
- 2026-05-27: P2 Qwen-only hardening started.
  - Added deterministic critical-facts extraction from Qwen window notes.
  - Qwen final assembly input now includes a Critical Facts Checklist before window notes.
  - Final assembly prompt now requires a dedicated `## 5. 技术资产附录：Prompts / Code / Config` section and non-overlapping chronological chapters.
  - Added Qwen-only QC for fact retention, timeline overlaps, and technical asset appendix presence.
  - Resume-mode usage accounting now separates `current_run_usage` from `end_to_end_usage` and includes reused window-note metadata.
  - Verified with `python3 -m py_compile` and offline checks against the WIN qwen-sw artifacts: old output is correctly flagged for missing `75分`, timeline overlaps, and missing technical asset appendix.
- 2026-05-27: Long narrative retention hardening.
  - Added `Narrative Evidence Blocks` to the Qwen window-note contract.
  - Final assembly input now includes narrative evidence blocks.
  - Final assembly prompt requires each chapter to include `叙事证据摘录` and requires `## 6. 叙事证据附录`.
  - Added `qwen_narrative_retention_qc` with body/transcript ratio and narrative-block retention metrics.
  - Added deterministic narrative appendix fallback so long-form story evidence can be appended without extra model calls when Qwen compresses it.
- 2026-05-27: Balanced frame quota tuning.
  - Changed frame downsampling from slide-first fill to balanced type quotas.
  - When a provider image cap forces sampling, selected frames reserve representative context coverage instead of letting slide anchors consume the whole cap.
  - Kept chronological output order after per-type even sampling.
  - Bumped `QWEN_WINDOW_NOTE_VERSION` to `qwen-window-note-v2` so old window notes are not reused after the Narrative Evidence Blocks prompt change.

## P2: Single-Provider Qwen Hardening

- [x] Add a deterministic critical-facts extractor over Qwen window notes.
  - Extract numbers, scores, dates, costs, tool names, people/project labels, and prompt/config/code blocks before final assembly.
  - Produce a machine-readable checklist that final assembly must satisfy.
  - Required facts for the validated live source include `75分`, `所见即所得`, `不要替换`, `34岁`, `2017年`, `年终奖`, `99.9%`, `4万积分`, `19.9万积分`, `Remotion`, `Coze/扣子`, and `Context Compression`.

- [x] Add a Qwen-only final assembly contract.
  - Inputs:
    - Qwen window notes.
    - Deterministic critical-facts checklist.
    - Deterministic transcript and visual evidence indexes.
  - Output:
    - `Markdowns/TTS_stream-{base}-qwen-sw.md`.
  - Requirements:
    - Strong Glossary / retrieval index at the head.
    - Detail-rich timeline body that accounts for every critical fact.
    - Dedicated `## 技术资产附录：Prompts / Code / Config` section assembled from Qwen window notes.
    - Non-overlapping chronological chapters.

- [x] Add Qwen-only QC.
  - Verify Qwen Glossary exists.
  - Verify the technical asset appendix includes required prompt/code/config blocks.
  - Verify every critical fact from the checklist appears in the final Markdown.
  - Verify final timeline chapters do not overlap.
  - Replace the current body/transcript ratio warning with an evidence-retention score; body ratio can remain a secondary metric.

- [x] Aggregate Qwen usage correctly.
  - In resume mode, read reused window-note metadata and include those calls in `end_to_end_usage`.
  - Keep `current_run_usage` separate so cost accounting is clear.

- [x] Add long narrative retention.
  - Window notes now require `Narrative Evidence Blocks`.
  - Qwen final assembly receives narrative evidence before window notes.
  - QC checks `qwen_narrative_retention_qc`.
  - If Qwen final assembly still compresses long stories, the script deterministically appends `## 6. 叙事证据附录`.

- [x] Add balanced frame quota tuning.
  - Frame downsampling now allocates roughly 55% slide, 25% annotation, and 20% context when frames exceed the image cap.
  - Each type is sampled evenly across time before the selected frames are restored to chronological order.
  - This prevents slide anchors from starving representative context frames in long-window or constrained-cap runs.

## P3: Optional Offline Benchmarking

- [ ] Keep Gemini comparison as an offline analysis tool, not a production dependency.
  - Inputs:
    - Gemini Markdown, only when it already exists from a separate evaluation run.
    - Qwen one-shot Markdown.
    - Qwen sliding-window Markdown.
    - Qwen window notes.
  - Output:
    - A comparison report, not a merged production Markdown.
  - Guardrail:
    - Do not call Gemini from the Qwen production path.
    - Do not require Gemini output to generate Qwen production Markdown.
    - Only revisit mixed-model output if the project later has a paid Gemini API budget and explicit approval.

- [ ] Add comparative scoring for future A/B runs.
  - Detail retention score.
  - Code/prompt preservation score.
  - Case-depth score.
  - Visual evidence coverage score.
  - NotebookLM retrieval-readiness score.

- [ ] Consider a human-review diff report.
  - Compare Qwen final against Gemini final or against window notes.
  - Highlight dropped prompts, dropped numbers, missing sections, and shortened examples.

## Proposed Implementation Order

1. P0 prompt/output contract fixes.
2. Qwen QC gates for current one-shot output.
3. Dynamic window builder and window-note persistence.
4. Qwen sliding-window extraction pass.
5. Final assembly pass from window notes.
6. Resume/caching for window notes.
7. Deterministic critical-facts extractor over Qwen window notes.
8. Qwen-only final assembly hardening: fact checklist, technical asset appendix, non-overlap timeline, usage aggregation, revised compression QC.
9. Optional offline comparison reports against Gemini artifacts when those artifacts already exist.

## Success Criteria

For the `live-ab-20260526` source:

- Qwen sliding-window mode covers all 439 frames across calls.
- Final Qwen Markdown includes an H1.
- Body length is closer to Gemini output and no longer looks like an executive summary.
- Coze repair prompt/code block is preserved.
- 学员2猫咪播客评分 `75分` and reasoning are preserved.
- Flow rewrite case keeps concrete personal-experience details.
- Final QC has no missing-heading, tail-coverage, frame-coverage, or code-block-retention warnings.
- Qwen-only final Markdown contains a strong Glossary, a detail-rich body, and a dedicated technical asset appendix extracted from Qwen window notes.
- Qwen QC confirms key facts from Qwen window notes are retained, especially `75分`, `所见即所得`, `不要替换`, `34岁`, `2017年`, and `年终奖`.

## Guardrails

- Do not add default-on multi-call synthesis to BAT.
- Do not enable Qwen sliding-window mode just because `DASHSCOPE_API_KEY` exists.
- Do not reuse Gemini free-tier multi-request assumptions for Qwen without explicit budget logging.
- Do not make production Markdown generation depend on both Gemini and Qwen. Mixed-model output is not allowed under the current free-tier/cost constraints unless the user explicitly approves it after a paid Gemini API upgrade.
- Do not remove the deterministic full transcript and visual evidence appendices.

## Discussion Summary For Next Session

Date: 2026-05-26

What was validated:

- WIN first produced the same-live-source Gemini/Qwen A/B outputs.
- Gemini one-shot remained the best NotebookLM source because it preserved narrative context, case texture, original wording, long examples, and concrete details.
- Qwen one-shot was cleaner but over-compressed, missed H1, dropped prompt/code blocks, and only used 250/439 frames due DashScope's image input cap.
- Qwen sliding-window was implemented and validated by WIN.
  - It covered all 439 frames across 3 windows.
  - It generated window notes and reused them with `--resume-window-notes`.
  - It restored late-stream content that one-shot compressed or missed.
  - It preserved prompt/code/config blocks much better, including the Coze "所见即所得 / 不要替换" repair prompt and the cat-podcast camera-control prompt.

What improved:

- Qwen sliding-window fixed the frame coverage problem.
- Qwen sliding-window fixed most long-tail forgetting.
- Qwen sliding-window output now has H1, stronger Glossary, code blocks, and a `qwen_window_coverage` marker.
- Qwen is valuable as a structured Chinese indexer and technical asset extractor.

What still failed:

- Final Qwen assembly still over-compressed prose compared with Gemini.
- Window note 001 preserved `75分`, but the final qwen-sw Markdown dropped it. This proves extraction worked and final assembly lost a critical fact.
- The final qwen-sw timeline produced overlapping chapters around `01:42 - 02:10`.
- `qwen_overcompressed_body` currently uses an overly blunt body/transcript ratio threshold; it should become an evidence-retention score.
- Resume-mode QC currently reports only final assembly usage unless reused window-note metadata is separately aggregated.

Important correction:

- Gemini's evaluator suggested a hybrid document: Gemini body + Qwen Glossary + Qwen technical assets.
- That may be a good manual NotebookLM experiment, but it is not acceptable as the production engineering path under current API/cost constraints.
- Calling two large models and then merging their outputs is too expensive and violates the project's engineering requirement unless the project later upgrades to a paid Gemini API plan and explicitly approves mixed-model generation.
- Production must stay single-provider:

```text
Qwen dynamic sliding-window notes
  -> deterministic critical-facts checklist
  -> Qwen-only final assembly
  -> Qwen-only NotebookLM Markdown with technical asset appendix
```

Tomorrow's recommended starting point:

1. Implement the deterministic critical-facts extractor over Qwen window notes.
2. Add Qwen-only final assembly requirements:
   - account for every critical fact;
   - emit a dedicated technical asset appendix;
   - produce non-overlapping chronological chapters.
3. Update Qwen QC:
   - fact retention score;
   - technical asset appendix checks;
   - timeline overlap detection;
   - end-to-end usage aggregation from reused window notes.
4. Keep Gemini as an offline comparison artifact only, not a production dependency.
