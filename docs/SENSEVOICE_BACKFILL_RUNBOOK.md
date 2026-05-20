# SenseVoice Backfill Runbook

Date: 2026-05-17

## Purpose

This branch uses FunASR SenseVoice as the default transcription backend for local MP4 processing and historical transcript backfill.

Use this branch for:

- Local video files under `Videos/`
- New Markdown generation with complete transcript appendices
- Historical Markdown transcript appendix backfill
- Re-transcribing old Whisper transcripts with SenseVoice

Do not use this branch for remote live-stream validation.

## Backend

Default:

```powershell
$env:TRANSCRIBE_BACKEND = "sensevoice"
```

Optional model settings:

```powershell
$env:SENSEVOICE_MODEL = "iic/SenseVoiceSmall"
$env:SENSEVOICE_VAD_MODEL = "fsmn-vad"
$env:SENSEVOICE_DEVICE = "cpu"
```

Legacy Whisper settings are still available for fallback/testing:

```powershell
$env:TRANSCRIBE_BACKEND = "cpu"
$env:TRANSCRIBE_BACKEND = "whispercpp-vulkan"
```

## Install

Windows may reuse the validated local SenseVoice environment if already present.

If installing from this branch:

```powershell
pip install -r requirements.txt
```

If PyTorch/Torchaudio need manual CPU wheels, install them in the same virtual environment before running backfill.

## Backfill Missing Transcript Appendices

Use this when Markdown files do not yet contain the complete transcript appendix:

```powershell
git fetch origin
git switch feature/local-transcript-appendix
git pull --ff-only
$env:TRANSCRIBE_BACKEND = "sensevoice"
python zhihuTTS.py --backfill-transcripts --transcribe-missing
```

The command will ignore old Whisper transcript caches when they do not match the requested backend and re-transcribe from local MP4 files.

## Refresh Existing Whisper Appendices

Use this only when existing transcript appendices should be replaced with SenseVoice output:

```powershell
$env:TRANSCRIBE_BACKEND = "sensevoice"
python zhihuTTS.py --backfill-transcripts --transcribe-missing --force-transcribe --refresh-transcripts
```

This rewrites the transcript appendix section in matching Markdown files.

## Notes

- SenseVoice is now the default backend on this branch.
- Cached transcripts include `backend_used`.
- Existing transcript caches from Whisper are treated as backend mismatches when SenseVoice is requested.
- The output shape remains compatible with the existing pipeline: `segments[{start,end,text,words}]`.
- Product and technical terms are normalized after ASR, including Cursor, Claude Code, MiniMax Agent, RAG, MCP, CLI, API, web coding, and AI coding.
