# QWEN Sliding-Window Verification — Replay vs Live Comparison

**Date**: 2026-05-27
**Operator**: WIN machine (zhihu-windows-runner)
**Source**: MAC user pushed QWEN optimization commits on `origin/main`

## Commits Verified

| Commit | Description |
|--------|-------------|
| `dd0c8a1` | feat: add qwen sliding-window synthesis |
| `9ce5054` | fix: cap Qwen hard limit to 250 data-uri |
| `2d94ea3` | feat: harden qwen sliding-window retention |
| `c7943fe` | fix: invalidate stale qwen window notes |
| `8e7c600` | fix(utils): harden call_gemini/call_qwen retry & error handling |

## Verification Method

1. Downloaded replay video of last night's live stream (195MB MP4 from vzuu.com)
2. Extracted 324 keyframes via frame-diff analysis (43 slides, 145 annotations)
3. Transcribed 131 chunks (60s each, 7,834s total) with SenseVoice (merge_vad=true)
4. Ran QWEN sliding-window synthesis (3 windows, 128 frames each)
5. Compared against last night's live QWEN output AND Gemini baseline

## Replay Pipeline

```
replay-20260527-qwen-verify.mp4 (195MB, 2h10min)
  → extract_keyframes() → 324 frames (43 slides, 145 annotations)
  → SenseVoice × 131 chunks → 41,817 chars transcript
  → build_stream_markdown.py --provider qwen --synthesis-pass sliding-window
  → TTS_stream-replay-20260527-qwen-qwen-replay.md (110,507 chars)
```

## Comparison Results

| Metric | Live QWEN (old) | Replay QWEN (new) | Δ | Live Gemini |
|--------|----------------|-------------------|---|---|-------------|
| CJK chars | 39,326 | **46,981** | +19.5% | 38,095 |
| Body chars | 111,559 | 110,064 | -1.3% | 107,888 |
| Overcompression | ⚠️ 0.24 ratio | **OK** | FIXED | OK |
| Glossary terms | 6 | **9** | +50% | 0 |
| H3 sections | 13 | 8 | -38% | 7 |
| Code blocks | 7 | 4 | -43% | 2 |
| Transcript chars | 41,749 | 41,817 | +0.2% | 41,749 |
| Keyframes | 439 | 324 | -115 | 439 |
| Fact retention | N/A | ⚠️ 67% | NEW ISSUE | N/A |

## Key Findings

### ✅ FIXED: Overcompression (body/transcript ratio)
Old QWEN flagged at 0.24 (below 0.35 minimum). New hardening commits resolve this.

### ✅ IMPROVED: Content density
+19.5% CJK characters vs old QWEN, +23% vs Gemini — richer detail preservation.

### ⚠️ NEW: Fact retention at 67% (target ≥90%)
Missing terms: 2017年, 15秒, 30秒, 1分钟, 3分钟, 35岁, 99%, 60分
Root cause: 324 replay frames vs 439 live frames. The frame-diff keyframe extraction
kept only 4.1% of frames, losing visual evidence for some critical facts.

### ⚠️ NEW: Fewer code blocks (4 vs 7)
Less prompt/code/config preservation in replay output.

## Artifacts

### Final Output
- `Markdowns/TTS_stream-replay-20260527-qwen-qwen-replay.md` — 110,507 chars

### Window Notes (sliding-window intermediate)
- `runs/stream-replay-20260527-qwen-*-qwen-window-001.notes.md` — 5,035 chars
- `runs/stream-replay-20260527-qwen-*-qwen-window-002.notes.md` — 3,990 chars
- `runs/stream-replay-20260527-qwen-*-qwen-window-003.notes.md` — 3,525 chars

### QC & Metadata
- `runs/stream-replay-20260527-qwen-*-qwen-replay.final-qc.json` — Full QC manifest
- `runs/stream-replay-20260527-qwen-*.manifest.json` — Run manifest
- `runs/stream-replay-20260527-qwen-*.combined-transcript.txt` — 41,817 chars

### Baselines (for comparison)
- `runs/baseline-live-ab-20260526-qwen-sw.md` — Last night's live QWEN output
- `runs/baseline-live-ab-20260526-gemini.md` — Last night's live Gemini output
- `runs/comparison-report-replay-vs-live.txt` — Automated comparison report

### Code
- `compare_qwen_outputs.py` — Comparison tool
- `process_replay_qwen.py` — Replay → chunk pipeline

## Action Items for MAC

1. Investigate fact retention drop — increase frame count or adjust QWEN_CRITICAL_FACT_TERMS
2. Consider raising QWEN_WINDOW_TARGET_FRAMES from 200 to cover more visual evidence
3. Review code block preservation — may need prompt tuning for code/config extraction
