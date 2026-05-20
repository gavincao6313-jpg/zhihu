# MAC Pipeline Verification Report

> Date: 2026-05-20
> Branch: `experiment/inline-and-uri-upload` (MAC)
> Tester: Windows runner
> Purpose: Verify MAC's direct-video-to-Gemini pipeline on Windows

## Test Setup

- **Test video**: 产品设计运营_08_【李智勇】全AI驱动的商业体与无人公司的案例与实践.mp4
  - Duration: 40.7 min, Size: 45.9 MB
- **Chunking**: 5-min segments → 9 parts (part000~part008), 5-6 MB each
- **Upload mode**: `files_api` (default)
- **Models tested**: gemini-2.5-flash, gemini-3.5-flash
- **Script**: `zhihuTTS.py` + `upload_parts.py` from `experiment/inline-and-uri-upload`

## Pipeline Verification

### ✅ Upload Phase — Passed
- Parallel upload (UPLOAD_WORKERS=2), speed 2-11 MB/s
- Progress tracking (_ProgressFile wrapper, per-5% logging)
- Upload retry on SSL EOF (part003/006/007/008 all had transient SSL failures, retried successfully)
- Cloud processing poll (files.get until ACTIVE)

### ✅ Retry Logic — Passed
- `_parse_retry_delay()` correctly parses `RetryInfo.retryDelay` from 429 errors
- Upload retry (inner, per-file) and generate retry (outer, whole video) work independently
- SSL/500/503/429 all handled gracefully

### ✅ Resume/Recovery — Passed
- `_recover_generated_parts()` scans `<!-- ===== Part N/Total ===== -->` markers
- After failure, re-run auto-detects already-completed parts and skips them
- Each retry only re-uploads (files_api requires fresh upload), then jumps to first incomplete part

### ✅ Cleanup — Passed
- `_cleanup_cloud_files()` deletes uploaded files via `files.delete()` on both success and failure paths

### ⚠️ Generate Phase — Model Instability
- `gemini-2.5-flash`: 503 UNAVAILABLE ×6, all retries exhausted (0 parts generated)
- `gemini-3.5-flash`: works but unstable — 500 INTERNAL + SSL EOF + 503 alternating
- Success pattern: ~5-6 retries needed to get through ONE part
- **Result**: 5/9 parts completed (parts 1-5), remaining 4 parts blocked by daily quota

## Issues Discovered

### 🔴 P0: Part granularity wastes daily quota

Current chunk size (5 min) produces too many parts → too many API calls.

- 40-min video → 9 parts → 9 `generate_content` calls (minimum)
- With retries: 5-6 attempts per part → 25-30 actual calls
- `gemini-3.5-flash` free tier: **only 20 generate_content calls/day**
- `gemini-2.5-flash` free tier: 1,500 calls/day but 503 overloaded

**Fix needed**: Gemini 2.5 Flash supports up to 1-hour video input. For most videos (<1h), no chunking needed at all — one file, one call. For 2-3h videos, chunk into 30-60 min segments, not 5 min.

### 🟡 P1: MAX_RETRIES default too low for current model stability

Default `MAX_RETRIES=6` with 65s delay gives ~6.5 min of retry. With current 500/503 frequency, this gets through only 1-2 parts per run. Increased to 12 for testing, which got through 2-3 parts.

**Suggestion**: Keep 12 as default, or make it a CLI/env var. Also consider: if a part succeeds after N retries, should the outer MAX_RETRIES counter reset? Currently the outer loop retries the ENTIRE video on any failure, so early parts burn retries that later parts can't use.

### 🟡 P2: files_api mode requires full re-upload on every outer retry

On every outer retry attempt, all 9 parts are re-uploaded via `files.upload()` because `uploaded_files` dict resets. This wastes bandwidth and time. `file_uri` mode avoids this but requires GitHub Release setup.

### 🟢 P3: caffeinate macOS-only, Windows crashes

`subprocess.Popen(["caffeinate", "-i"])` throws FileNotFoundError on Windows. Fixed locally with try/except. Should be in the main script.

### 🟢 P4: Output has duplicate metadata per part

Each part generates its own metadata section, glossary, and "遗留问题". When 9 parts are appended, the final .md has 9 separate glossaries. Need a final merge pass.

## Discussion Summary

### Part consolidation
Instead of 5-min parts, use fewer larger segments. Most videos <1h → no chunking. Long videos → 3-4 segments max. This keeps daily API calls within quota.

### Merge strategy (after all parts done)
Two options discussed:
- **A**: One-shot merge prompt — feed all 9 part outputs to Gemini for dedup + timeline merge
- **B**: Modified per-part prompts — Part 1 normal, Part 2-9 in "append mode" without metadata

Recommend A for simplicity.

### Windows/MAC coordination
- MAC's `experiment/inline-and-uri-upload` and Windows' `feature/local-transcript-appendix` have no shared merge base
- MAC pipeline is simpler (no local preprocessing), Windows pipeline has better quota tracking + CLI args
- If merging branches: keep MAC's direct-video-to-Gemini core, add Windows' CLI/progress infrastructure back

## API Quota Used Today

| Phase | Calls | Model |
|-------|-------|-------|
| Model scan | ~33 | various |
| Run 1 uploads | ~27 | Files API |
| Run 1 generate | 6 | gemini-2.5-flash |
| Run 2 uploads | ~29 | Files API |
| Run 2 generate | ~12 | gemini-3.5-flash |
| Run 3 uploads | ~29 | Files API |
| Run 3 generate | ~12 | gemini-3.5-flash |
| **Total generate** | **~30** | gemini-3.5-flash |
| **Daily limit** | **20** | gemini-3.5-flash |

Note: Files API (upload/get/delete) does NOT count toward `generate_content` quota.

## Next Steps

1. Tomorrow: resume Parts 6-9 with gemini-3.5-flash, then merge all 9 parts
2. MAC: increase default part size (5 min → 30-60 min or no-chunk for <1h videos)
3. MAC: increase MAX_RETRIES to 12 or add env var
4. MAC: add Windows caffeinate compatibility
5. After merge: decide whether to unify the two branches or keep MAC pipeline as main

## Generated Output

- `Markdowns/产品设计运营_08_test.md` — 5/9 parts, high quality structured knowledge base
  - Per-part structure: Metadata → Glossary → Detailed Content (with timestamps) → Visual Description → Open Questions
  - Ready for NotebookLM import after final merge
