# Live Stream Optimization Backlog

Date: 2026-05-21

Purpose: preserve the live/BAT/URL-branch optimization ideas so they can be discussed and decided one by one without losing the remaining items.

## Current Understanding

- `run_zhihu_live.bat` starts the Zhihu live workflow from a live room URL and saved Playwright auth state.
- `zhihuTTS_stream.py --playwright-keepalive` opens a Playwright page, captures fresh CC/FLV media URLs, and processes the stream in 60s chunks.
- A normal manually opened browser live window is not part of the processing chain.
- The Playwright keepalive page and the captured signed media URL are still important for later chunk refresh/recovery.
- If another machine login invalidates the Windows-side session or stream authorization, already captured chunks may continue briefly, but later slicing/refresh can fail.

## Backlog

### P0: Decouple Capture From Processing

Problem:

- The current loop effectively does: capture/slice one chunk, then transcribe/extract frames, then continue.
- For true live streams, if local transcription or frame extraction takes time, the pipeline can lag or potentially miss live content unless ffmpeg is independently recording continuously.

Proposal:

- Run ffmpeg as the continuous capture component.
- Write fixed-duration segment files, for example 60s chunks, into `Videos/.stream`.
- Run a separate processing worker that watches completed segment files and performs SenseVoice transcription, keyframe extraction, manifest writing, and later merge/Markdown generation.

Discussion points:

- Whether to implement this as one Python supervisor with two internal loops, or separate capture/worker scripts.
- How to mark a segment as complete before processing it.
- How to resume after interruption without duplicating segments.
- How much disk space to reserve before starting.

Initial design note:

- Do not consume a segment just because a file appears in the directory.
- Prefer an atomic completion signal:
  - HLS muxer with temporary segment files and final rename.
  - Or a producer-owned manifest/queue entry written only after the segment is closed.
- Consumer should process only completed segment names, then still validate with `ffprobe` before transcription.
- Partial temp files left by crashes should be ignored or quarantined on resume.

Follow-up discussion:

- `temp_file + m3u8` is a clean completion signal inside one uninterrupted ffmpeg session because ffmpeg writes a temporary segment, atomically renames it to the final `.ts`, then updates the playlist.
- `ffprobe` should remain as a third-line validation after the completion signal; duration checks should be lenient, for example process segments >= 10s so short final segments are not incorrectly discarded.
- URL expiry/restart changes the consumer design. A consumer that depends only on one `capture.m3u8` can become brittle across ffmpeg restarts.
- Prefer a directory/queue consumer:
  - Ignore temporary files.
  - Poll or watch final `.ts` files.
  - Sort by stable segment number or timestamp.
  - Use a processed set/checkpoint to avoid duplicates.
- Critical restart caveat: ffmpeg segment names must remain globally unique across restarts. Do not let a restarted ffmpeg reuse `seg_000000.ts` and overwrite old processed or queued segments. Options include supervisor-managed `-start_number`, timestamp/epoch-based segment filenames, or one subdirectory per capture session.
- Proposed thread model:
  - Thread A: Playwright/URL supervisor + ffmpeg process manager, restarts ffmpeg after URL expiry/failure.
  - Thread B: segment watcher, discovers completed final `.ts` files and enqueues them.
  - Thread C: processor, validates with ffprobe, transcribes, extracts frames, writes checkpoint, and logs/skips per-segment failures without stopping capture.

Agreed P0 design direction:

- Use session-epoch plus local index segment names:
  - `seg_{session_epoch}_{index:06d}.ts`
  - Example: `seg_1716339612_000000.ts`, `seg_1716339612_000001.ts`
  - After ffmpeg restart, start a new epoch: `seg_1716340284_000000.ts`
- Rationale:
  - No persistent global counter is required.
  - A supervisor crash/restart does not risk reusing old segment names as long as the new ffmpeg session gets a new epoch.
  - Lexicographic file ordering remains recording order: epoch first, local segment number second.
- ffmpeg should write one independent playlist per recorder session:
  - `seg_{session_epoch}_capture.m3u8`
  - The consumer does not depend on this playlist for discovery.
  - This avoids brittle behavior if ffmpeg restarts and rewrites/truncates a playlist.
- Proposed HLS flags:
  - Use `temp_file`.
  - Do not use `delete_segments`; the processor may still need older segment files.
  - Do not use `append_list` for the primary design; each ffmpeg run writes its own playlist.
  - `program_date_time` is not required because the filename epoch carries session timing.
- Suggested ffmpeg shape:

```text
ffmpeg
  -reconnect 1
  -reconnect_streamed 1
  -reconnect_delay_max 3
  -headers "<captured headers>"
  -i "<flv_url>"
  -c copy
  -f hls
  -hls_time 60
  -hls_list_size 0
  -hls_segment_type mpegts
  -hls_flags temp_file
  -hls_segment_filename "Videos/.stream/seg_{session_epoch}_%06d.ts"
  "Videos/.stream/seg_{session_epoch}_capture.m3u8"
```

Revised thread model:

- Use two primary threads rather than three for the first implementation.
- `Recorder` thread:
  - Owns Playwright keepalive/extraction and the ffmpeg subprocess.
  - Starts Playwright and captures the initial FLV URL.
  - Starts ffmpeg with a new `session_epoch` for each ffmpeg process.
  - If ffmpeg exits and DOM does not confirm stream ended, refreshes the Playwright page to get a new URL and starts a new ffmpeg session.
  - Sets a shared `recorder_stopped` event when recording is permanently done.
- `SegmentConsumer` thread:
  - Polls the output directory, for example every 5 seconds.
  - Processes final `seg_*.ts` files only; ignores temporary files.
  - Sorts by filename so segment order is stable.
  - Maintains a processed set from checkpoint state.
  - Runs `ffprobe` validation with a lenient minimum duration, for example 10 seconds.
  - Transcribes, extracts frames, writes per-segment outputs, and updates checkpoint.
  - Per-segment failures should be logged and retried with a retry cap; they should not stop the recorder.

Exit coordination:

- `Recorder` and `SegmentConsumer` share a `threading.Event`.
- Main flow starts both, waits for `Recorder.join()`, then waits for `SegmentConsumer.join()`.
- Consumer exits only when `recorder_stopped` is set and no unprocessed final segments remain.
- This preserves tail segments after live recording ends.

Stream-end authority:

- Do not rely on ffmpeg return code alone to decide live completion.
- `returncode == 0` can mean clean stream close, but stream-end behavior can vary.
- DOM-based `PlaywrightKeepaliveStream.is_stream_ended()` remains the authoritative end signal where available.
- ffmpeg non-zero exit generally means refresh/restart unless DOM confirms the stream ended or refresh fails permanently.

Confirmed architecture constraint:

- Existing code does not proxy media through Playwright.
- Playwright captures signed CC/FLV URL and request headers.
- ffmpeg connects directly to the captured FLV URL.
- Therefore the recorder can treat Playwright as URL/session supervisor and ffmpeg as the independent media capture process.

Next design question:

- Identify which existing `zhihuTTS_stream.py` functions can be reused directly and which need to be refactored or replaced for the continuous-recorder architecture.

Reuse/refactor boundary analysis:

- Keep/reuse directly:
  - `stream_extractors.ExtractedStream`
  - `stream_extractors.PlaywrightKeepaliveStream`
  - `PlaywrightKeepaliveStream.start()`, `refresh_and_get()`, `is_stream_ended()`, `mark_stream_active()`, `close()`, and `restart()`
  - `parse_time()`, `fmt_time()`, `safe_name()`
  - `parse_headers_text()`, `parse_headers_file()`, `overlay_headers()`
  - `build_ffmpeg_headers()` for ffmpeg `-headers`
  - `redacted_error()` style URL redaction
  - `zhihuTTS_video.transcribe_audio()`
  - `zhihuTTS_video.extract_keyframes()`
  - `zhihuTTS_video.transcript_to_text()`
  - `zhihuTTS_video.build_gemini_payload()`
  - `offset_transcript_text()` if the consumer provides the segment's global start offset
  - `write_report()` if the consumer preserves the current chunk data shape
  - `write_manifest()` if final `chunks` entries keep the current schema
  - `build_stream_gemini_parts()` if payload/global transcript paths remain compatible

- Reuse with small adaptation:
  - `process_slice()` should be split. Its processing half is valuable, but its remote slicing call must be removed. New shape: `process_segment_file(segment_path, start_s, duration_s, chunk_index, ...)`.
  - The output naming should stay compatible with existing downstream scripts: `stream-{base}_chunk{global_index:03d}_{start_s}s-...`. The source segment can be `seg_{epoch}_{local_index}.ts`; downstream outputs do not need to expose that name.
  - `probe_url()` / `summarize_probe()` are still useful for initial stream diagnostics, but the consumer needs a separate `ffprobe_segment()` for local `.ts` validation.
  - `scripts/merge_stream_chunks.py` and `scripts/build_stream_markdown.py` can remain mostly unchanged if per-segment output filenames and payload JSON structure remain compatible.

- Replace/obsolete in continuous mode:
  - `slice_url()` is replaced by the `Recorder` ffmpeg HLS session command.
  - `process_slice_with_recovery()` is obsolete because URL refresh/restart moves to `Recorder`.
  - The chunk loop inside `run_validation()` is replaced by orchestration that starts `Recorder` and `SegmentConsumer`, waits for both, then finalizes combined transcript/manifest.
  - Current checkpoint logic that only writes `{"chunks": ...}` after each processed chunk needs to become a richer checkpoint with processed source segment names, retry counts, chunk records, and cumulative offsets.

- New code likely needed:
  - `Recorder` thread/class.
  - `SegmentConsumer` thread/class.
  - `run_ffmpeg_hls_session(stream, session_epoch, output_dir, segment_seconds)`.
  - `scan_completed_segments(output_dir, processed_set)`.
  - `parse_segment_key("seg_{epoch}_{index}.ts")`.
  - `ffprobe_segment(path, min_duration_s=10)`.
  - `process_segment_file(...)` extracted from `process_slice()`.
  - Atomic checkpoint read/write helpers.
  - Finalizer that combines chunk outputs and writes manifest after recorder stops and backlog drains.

- Important timestamp decision:
  - Segment filename epoch/local-index is for stable ordering and uniqueness, not necessarily for transcript timestamps.
  - Global transcript offsets should come from the consumer's ordered processed chunks and measured/accepted segment durations.
  - Store `start_s` and `duration_s` per segment in checkpoint/chunk records so resume can preserve timestamp continuity.

- Low-risk migration path:
  - First extract `process_segment_file()` while keeping the old `process_slice()` behavior.
  - Add continuous HLS mode behind an explicit flag, for example `--continuous-hls`, without removing the current URL-slice mode.
  - Keep BAT on existing mode until one full replay/live validation passes.
  - After validation, switch `run_zhihu_live.bat` to the continuous mode.

Implementation boundary refinements:

- Proposed `process_segment_file()` signature:

```python
def process_segment_file(
    segment_path: Path,
    start_s: float,
    duration_s: float,
    chunk_index: int,
    base: str,
    runs_dir: Path,
    gemini_client=None,
) -> ChunkRecord:
    ...
```

- `start_s` is the global transcript offset computed by `SegmentConsumer`.
- `duration_s` must come from local segment `ffprobe`, not from configured `hls_time`; final or interrupted segments may be much shorter than 60s.
- `chunk_index` is the consumer-maintained global sequence number, preferably 0-based internally while output filenames can remain compatible with current chunk numbering.
- `gemini_client` should remain optional and usually `None`; final NotebookLM generation should continue as the single downstream synthesis path unless explicitly changed.

Segment input compatibility:

- Current `zhihuTTS_video.transcribe_audio()` extracts a temporary 16kHz mono WAV with ffmpeg before calling the transcription backend, so `.ts -> ffmpeg -> WAV -> SenseVoice` should work without passing `.ts` directly to SenseVoice.
- `extract_keyframes()` also uses ffmpeg on the input video path, so MPEG-TS input should be supported in principle.
- First validation after extracting `process_segment_file()` should explicitly run one `.ts` segment through `transcribe_audio()` and `extract_keyframes()` to confirm Windows ffmpeg/container behavior.

Checkpoint ordering requirement:

- Consumer must write or preserve the segment's `start_s` before invoking transcription.
- Proposed order:
  - Discover completed final segment.
  - Assign or load `start_s` from checkpoint.
  - Run `ffprobe` to measure `duration_s`.
  - Write checkpoint entry with filename, `start_s`, `duration_s`, and status such as `processing`.
  - Call `process_segment_file(...)`.
  - Update status to `done` and attach the returned chunk record.
- Rationale: if SenseVoice or frame extraction crashes, resume can reuse the same `start_s` instead of recomputing a shifted timeline.

Recorder restart gaps:

- If ffmpeg stops and URL refresh takes time, that wall-clock gap has no media segment.
- Preferred design: do not insert synthetic transcript chunks. Continue transcript `start_s` from the accumulated media duration, and record `gap_before_s` metadata on the next segment/chunk.
- This keeps downstream merge scripts simple while preserving gap visibility in manifest/checkpoint.
- A future enhancement can insert explicit gap records in the manifest if needed.

CLI/BAT rollout:

- Add `--continuous-hls` to `zhihuTTS_stream.py`.
- Existing URL-slice behavior remains default.
- BAT can switch by adding one flag in the worker command after validation.

Narrow Step 1:

- Step 1 should be pure code reorganization with no behavior change:
  - Extract the processing half of `process_slice()` into `process_segment_file()`.
  - Keep `process_slice()` doing the same remote slice operation first.
  - Have `process_slice()` call `process_segment_file()` on the generated local file.
  - Run the existing mode and compare outputs/log shape before implementing `Recorder` and `SegmentConsumer`.

Step 1 implementation scope:

- Modify only `zhihuTTS_stream.py`.
- Add `process_segment_file(...)` by extracting the current post-`slice_url()` half of `process_slice()`.
- Keep `process_slice_with_recovery()`, `run_validation()`, checkpoint format, BAT files, and downstream scripts unchanged.
- Proposed Step 1 signature:

```python
def process_segment_file(
    segment_path: Path,
    start_s: float,
    duration_s: float,
    chunk_index: int,
    chunk_total: int,
    base_stem: str,
    args: argparse.Namespace,
    host: str,
    source_summary: dict,
    headers: dict[str, str],
    reextracts: int = 0,
    recovery_errors: list[str] | None = None,
) -> dict | None:
    ...
```

- In Step 1, keep `args: argparse.Namespace` rather than splitting out `cleanup_slices`; this minimizes behavior and call-shape changes.
- `process_slice()` should continue to build the same `slice_stem`, create the same `.mp4` path, print the same slicing line, call `slice_url()`, then delegate to `process_segment_file()`.

Step 1 validation standard:

- Output filename format remains identical.
- Manifest chunk count remains identical for the same replay/input.
- `transcript_chars` differs by less than 1%, allowing transcription nondeterminism.
- Manifest JSON top-level keys remain identical.
- One local `.ts` segment should be manually passed through `process_segment_file()` or its core path to confirm ffmpeg-based WAV extraction and keyframe extraction work with MPEG-TS input.

Step 2 implementation scope:

- Modify `zhihuTTS_stream.py` for the new entry path.
- Keep old URL-slice mode as the default.
- Add constants:
  - `HLS_SEGMENT_POLL_S = 5`
  - `HLS_MIN_DURATION_S = 10`
- Add CLI flag:
  - `--continuous-hls`
- Add `Recorder` class:
  - Owns Playwright keepalive and ffmpeg HLS process management.
  - Starts ffmpeg with `hls_flags temp_file`, `seg_{epoch}_%06d.ts`, and independent per-session m3u8.
  - On ffmpeg abnormal exit, refreshes URL through Playwright and restarts with a new epoch unless DOM confirms stream ended.
- Add `SegmentConsumer` class:
  - Polls completed final `.ts` files and ignores temp files.
  - Sorts by filename.
  - Runs local ffprobe validation: duration >= `HLS_MIN_DURATION_S` and audio stream exists.
  - Writes segment `start_s` to checkpoint before calling `process_segment_file()`.
  - Processes backlog until recorder stopped and no unprocessed segments remain.
- Add continuous-mode checkpoint schema containing:
  - `processed_segments`
  - `failed_segments`
  - `timeline`
  - chunk records for final manifest generation
- Add `run_continuous_hls(args)` and dispatch from `main()` only when `args.continuous_hls` is true.
- Do not change `run_zhihu_live.bat` until Step 4; Step 2 and Step 3 should be tested through manual command-line runs.

Step 2 validation standard:

- Old path without `--continuous-hls` remains identical to Step 1.
- Recorder creates `seg_*.ts` files in the configured stream work directory.
- Consumer never reads temp files.
- Manifest chunk order follows filename lexicographic order.
- `start_s` accumulation error stays below 1s per chunk against ffprobe durations.
- Tail segments are processed after recorder stops.
- Crash/resume uses checkpoint without duplicate processing.

Implementation choices confirmed for discussion:

- Keep `args: argparse.Namespace` in Step 1; revisit decoupling after the pure refactor passes validation.
- Prefer class-based `Recorder` and `SegmentConsumer` in Step 2 because lifecycle state, retry counters, subprocess handles, and checkpoint state will grow.

### P1: Use a Dedicated Windows Runner Account

Problem:

- Same-account playback/login on another machine may invalidate or disturb the Windows-side session or live authorization.
- Code can retry and refresh, but cannot guarantee platform session policy.

Proposal:

- Use a dedicated account for Windows live processing.
- Do not enter the same live room with that account from another machine during capture.
- Keep `zhihu_auth_state.json` specific to the runner account.

Discussion points:

- Whether a dedicated account is available and allowed for the courses/live rooms.
- Whether the Windows runner should refresh auth shortly before every live session.
- Whether to add account identity display/checks in startup logs.

### P1: Formalize the Background BAT Worker Mode

Problem:

- There are two BAT behaviors in circulation: foreground run and background worker plus log-tail monitor.
- Closing the wrong window can terminate the real job.

Proposal:

- Standardize `run_zhihu_live.bat` on MAIN/WORKER mode.
- MAIN validates input and starts a separate worker window.
- MAIN tails the log and can be closed safely.
- WORKER owns the real Python process and must not be closed.

Discussion points:

- Whether to keep the worker window visible or hidden.
- Whether to print worker PID/window title in logs.
- Whether to write a `.pid` or `.status.json` file for monitoring.
- Whether to add clear startup text: "close monitor OK, close worker stops job."

### P1: Add Checkpoint Resume

Problem:

- The stream runner writes checkpoint/progress artifacts, but restart/resume is not yet a first-class user workflow.
- A browser crash, auth expiry, network interruption, or Windows restart can force manual recovery.

Proposal:

- Add `--resume` support to continue from completed chunks for the same `NAME`.
- BAT example: `run_zhihu_live.bat <URL> <NAME> --resume`.
- Resume should skip already processed chunks and append new chunks cleanly.

Discussion points:

- What is the source of truth: checkpoint JSON, manifest JSON, segment files, or combined transcript.
- How to handle live streams where wall-clock time moved forward while the process was down.
- Whether resume means "continue from last captured segment" or "recover final document from existing chunks."

Current checkpoint behavior in `run_validation()`:

- Path: `runs/stream-{base_stem}.checkpoint.json`.
- Created only after a chunk returns a non-`None` chunk record and is appended to the in-memory `chunks` list.
- Current payload shape:

```json
{
  "chunks": [/* completed chunk records */],
  "created_at": "ISO timestamp from run start"
}
```

- Silent chunks that return `None` are not recorded.
- The checkpoint does not record current `chunk_index`, next start time, retry state, latest stream URL, browser restart count, original args, or final manifest paths.
- On handled loop exits such as stream ended, permanent slice failure, browser-restart exhaustion, or Ctrl-C, the code continues to finalization and writes combined transcript plus manifest from the in-memory `chunks`.
- After final manifest write, `checkpoint_path.unlink(missing_ok=True)` deletes the checkpoint.
- If the process crashes or the Windows process is killed before finalization, the checkpoint can remain on disk and contains completed chunks up to the last successful write.

Current capability boundary:

- The current checkpoint is useful as an emergency progress snapshot after an abrupt process death.
- It is not currently consumed by startup logic, so there is no automatic resume.
- There is no `--resume` CLI flag.
- A rerun with the same `--name` starts with `chunks = []` and a fresh `chunk_index = 0`; it does not load the checkpoint.
- Finalization already makes checkpoint redundant on handled exits because manifest/combined transcript are written before checkpoint deletion.
- Resume design must add explicit loading, validation, next-chunk calculation, and duplicate-output handling.

P1-C proposed resume design:

- Add `--resume` to `zhihuTTS_stream.py`.
- On startup, after `base_stem` and `checkpoint_path` are known:
  - If `--resume` is set and checkpoint exists, load it.
  - Restore `chunks` from `checkpoint["chunks"]`.
  - Restore `created_at` from `checkpoint["created_at"]`.
  - Resume from END time:
    - `last = chunks[-1]["slice"]`
    - `start_s = last["start_s"] + last["duration_s"]`
    - `chunk_index = chunks[-1]["chunk"]["index"]`
  - Continue loop from the next chunk.
- END-time resume is preferred because checkpoint is written only after a chunk has fully processed. Replaying from START time would require transcript deduplication and creates more complexity than value.
- Combined transcript after resume:
  - Existing chunk dicts in checkpoint already include `global_transcript_text`.
  - Pre-resume text can be assembled directly from checkpoint chunks.
  - New chunks can still read their `global_transcript_txt` files as today, or finalization can consistently use `chunk["global_transcript_text"]` when present.
  - This means resume can work even when `--cleanup-slices` removed per-chunk output files after checkpoint write.
- BAT support:
  - Add a `RESUME_FLAG` and pass it through to `zhihuTTS_stream.py`.
  - Simple fixed positional form is acceptable for first implementation: `run_zhihu_live.bat <URL> <NAME> --resume`.
  - Document that `--resume` must be the third argument.

P1-C validation ideas:

- Simulate abrupt process termination after at least two completed chunks and confirm checkpoint remains.
- Rerun with same `NAME --resume`.
- Confirm log reports resume chunk/time.
- Confirm the next processed chunk starts at `last.start_s + last.duration_s`.
- Confirm final manifest includes pre-resume and post-resume chunks with no duplicated chunk indices.
- Confirm combined transcript includes pre-resume text from checkpoint even if old per-chunk files are missing.

### P2: Proactive Stream URL Refresh

Problem:

- CC signed FLV URLs have an `auth_key` style lifetime.
- Current flow primarily refreshes after slicing failure.

Proposal:

- Record the time each media URL was captured.
- Proactively refresh the Playwright page every 30-60 minutes, or before expected URL expiry.
- If refresh fails but the old URL still works, continue with the old URL and retry refresh later.

Discussion points:

- What refresh interval is safest for CC/Zhihu without causing unnecessary risk.
- Whether to parse expiry from URL parameters if available.
- How to avoid losing a chunk during refresh.

### P2: Stronger Startup Diagnostics

Problem:

- Failure modes currently show up during the run.
- Some can be detected before the live session starts.

Proposal:

- BAT/Python startup should check:
  - `ffmpeg` and `ffprobe` availability.
  - Playwright installation and browser availability.
  - `zhihu_auth_state.json` contains `z_c0` and has enough remaining lifetime.
  - `Videos/.stream` is writable.
  - Free disk space is sufficient.
  - Active transcription backend.
  - Whether Gemini will run, and which script will call it.

Discussion points:

- Minimum disk space threshold.
- Whether warnings should block startup or only require confirmation.
- Whether API/Gemini checks should remain opt-in to avoid accidental usage.

Current BAT preflight:

- Python/venv selection exists.
- `zhihu_auth_state.json` existence check exists.
- Cookie validity check via `scripts/check_auth.py` exists.
- Gemini key status is printed.

P2-B proposed additional BAT-only preflight:

| Check | Method | Behavior |
|---|---|---|
| `ffmpeg` available | `where ffmpeg` | blocking |
| `ffprobe` available | `where ffprobe` | blocking |
| `Videos\.stream` writable | create/delete a small test file | blocking |
| disk free space | PowerShell `Get-PSDrive` or equivalent | warning only if below threshold |
| `TRANSCRIBE_BACKEND` | print env var/default | info only |

Implementation placement:

- Keep this in `run_zhihu_live.bat`; do not add a Python `preflight.py` for these simple checks.
- Insert after Python/auth-file checks and before `scripts/check_auth.py`.
- Rationale: the checks are shell-level dependencies and file-system probes; adding a Python helper would add another maintained entrypoint without enough benefit.

P2-B decisions:

- Blocking checks:
  - `ffmpeg` missing.
  - `ffprobe` missing.
  - Stream work directory cannot be created or written.
- Warning-only check:
  - Disk free space below 10GB. Warn loudly but do not block because short runs and low-bitrate streams may still be acceptable.
- Info-only:
  - Current `TRANSCRIBE_BACKEND`, including default when unset.
- Skip Playwright browser binary preflight in BAT for now:
  - Browser install paths are versioned and platform-specific.
  - Reliable detection in BAT would require brittle recursive PowerShell checks.
  - Playwright runtime error for missing browser executable is already explicit enough.
  - Revisit only if this becomes a recurring Windows runner failure.

### P2: Clearer Failure Classification

Problem:

- Several different situations can look like "no stream URL" or "ffmpeg failed."
- Better logs would speed up Windows-side decisions.

Proposal:

- Classify common failures:
  - Page redirected to login: account/session invalid.
  - Page OK but no media URL: not started, ended, blocked, or player not activated.
  - ffmpeg 401/403: media authorization expired or rejected.
  - ffmpeg timeout: network, stream stall, or server interruption.
  - Browser closed/unresponsive: Playwright keepalive failure.

Discussion points:

- Which exact stderr patterns should map to each status.
- Whether each status should stop, retry, refresh, or ask for manual intervention.
- Whether to write a structured final status JSON for run reports.

## Suggested Discussion Order

1. P0 decouple capture from processing.
2. P1 dedicated runner account.
3. P1 background BAT worker mode.
4. P1 checkpoint resume.
5. P2 proactive URL refresh.
6. P2 startup diagnostics.
7. P2 failure classification.
