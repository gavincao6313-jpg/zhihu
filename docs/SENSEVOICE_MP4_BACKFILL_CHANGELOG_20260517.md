# SenseVoice MP4 Backfill Change Log - 2026-05-17

## Context

Windows completed full replay-stream validation and separately tested FunASR SenseVoice on replay audio samples.

Findings from Windows:

- The replay stream pipeline completed end to end with the existing Whisper-compatible flow.
- Whisper/faster-whisper transcript quality was not good enough for Chinese lecture backfill.
- FunASR SenseVoice produced better Simplified Chinese output, punctuation, and readability.
- SenseVoice CPU inference on short samples was fast enough to justify using it as the primary ASR backend.

## Decision

Move local MP4 transcript generation and historical transcript backfill from Whisper-first behavior to SenseVoice-first behavior on:

```text
feature/local-transcript-appendix
```

The stream validation branch is not changed by this commit.

## Implementation Summary

Commit pushed:

```text
1d611f6 feat: use SenseVoice for transcript backfill
```

Branch pushed:

```text
feature/local-transcript-appendix
```

Changed behavior:

- `zhihuTTS_video.transcribe_audio()` now defaults to `TRANSCRIBE_BACKEND=sensevoice`.
- `TRANSCRIBE_BACKEND=cpu`, `TRANSCRIBE_BACKEND=whispercpp`, and `TRANSCRIBE_BACKEND=whispercpp-vulkan` remain available for fallback/testing.
- Local MP4 processing and historical Markdown backfill both share the same ASR backend.
- Transcript caches now check `backend_used` before reuse.
- Old Whisper/CPU caches are treated as mismatches when SenseVoice is requested.
- `--force-transcribe` can ignore old transcript caches.
- `--refresh-transcripts` can replace an existing transcript appendix.
- Product and technical terms are normalized after ASR, including Cursor, Claude Code, MiniMax Agent, RAG, MCP, CLI, API, web coding, and AI coding.

New documentation:

```text
docs/SENSEVOICE_BACKFILL_RUNBOOK.md
```

## Code Review And Verification

Pre-change impact analysis:

- `transcribe_audio()` is a high-impact shared function.
- Directly affected paths include local `zhihuTTS.py process_video`, historical transcript backfill, and `zhihuTTS_video.py` standalone use.
- The change was implemented as an additive backend switch while preserving the existing transcript shape.

Verification commands run:

```bash
python3 -m py_compile zhihuTTS.py zhihuTTS_video.py
python3 zhihuTTS.py --help
git diff --check
sh -n githooks/pre-commit
```

Additional helper checks:

- Appendix refresh helper replaces only the transcript appendix and preserves the Markdown body.
- Backend cache helper accepts SenseVoice caches and rejects old CPU/Whisper caches when SenseVoice is requested.
- `TRANSCRIBE_BACKEND=sensevoice` resolves to `sensevoice`.

## Windows Run Instructions

For missing transcript appendices:

```powershell
git fetch origin
git switch feature/local-transcript-appendix
git pull --ff-only
$env:TRANSCRIBE_BACKEND = "sensevoice"
python zhihuTTS.py --backfill-transcripts --transcribe-missing
```

To replace existing Whisper transcript appendices with SenseVoice output:

```powershell
$env:TRANSCRIBE_BACKEND = "sensevoice"
python zhihuTTS.py --backfill-transcripts --transcribe-missing --force-transcribe --refresh-transcripts
```

## Next Discussion Point

For the stream branch, the next decision is how to bring the same SenseVoice backend into:

```text
feature/stream-transcript-validation
```

Likely direction:

- Reuse the shared `zhihuTTS_video.transcribe_audio()` backend abstraction.
- Keep stream slicing/retry hardening from `5371c70`.
- Avoid duplicating SenseVoice code inside `zhihuTTS_stream.py`.
- Decide whether to merge the MP4 branch backend changes into the stream branch or cherry-pick the ASR backend pieces.
