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

## P2: Hybrid Output Strategy

- [ ] Support a "Qwen glossary over Gemini-style body" assembly mode.
  - Use Qwen to produce a strong Glossary and index.
  - Use faithful window notes to produce a detail-rich Gemini-style body.
  - This mirrors the Gemini evaluator recommendation: Qwen Glossary + Gemini-level detail retention.

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
7. Hybrid Glossary/body mode.

## Success Criteria

For the `live-ab-20260526` source:

- Qwen sliding-window mode covers all 439 frames across calls.
- Final Qwen Markdown includes an H1.
- Body length is closer to Gemini output and no longer looks like an executive summary.
- Coze repair prompt/code block is preserved.
- 学员2猫咪播客评分 `75分` and reasoning are preserved.
- Flow rewrite case keeps concrete personal-experience details.
- Final QC has no missing-heading, tail-coverage, frame-coverage, or code-block-retention warnings.

## Guardrails

- Do not add default-on multi-call synthesis to BAT.
- Do not enable Qwen sliding-window mode just because `DASHSCOPE_API_KEY` exists.
- Do not reuse Gemini free-tier multi-request assumptions for Qwen without explicit budget logging.
- Do not remove the deterministic full transcript and visual evidence appendices.
