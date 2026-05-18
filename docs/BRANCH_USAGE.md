# Branch Usage Guide

Date: 2026-05-18

This repository currently has two active feature branches with different purposes. Windows users should choose the branch by task, not by "newer commit".

## Fast Decision Table

| Task | Branch | Main command | Owner role |
|---|---|---|---|
| Process local MP4 files from `Videos/` | `feature/local-transcript-appendix` | `python zhihuTTS.py ...` | Windows production/backfill run |
| Add or refresh complete transcript appendix in existing Markdown | `feature/local-transcript-appendix` | `python zhihuTTS.py --backfill-transcripts ...` | Windows production/backfill run |
| Re-run historical Whisper transcripts with SenseVoice/FunASR | `feature/local-transcript-appendix` | `python zhihuTTS.py --backfill-transcripts --force-transcribe --refresh-transcripts` | Windows production/backfill run |
| Validate replay/live/remote media URL processing | `feature/stream-transcript-validation` | `python zhihuTTS_stream.py ...` | Windows validation run |
| Test live room URL extraction with yt-dlp or Playwright | `feature/stream-transcript-validation` | `python zhihuTTS_stream.py --page-url ...` | Windows validation run |
| Test URL expiration, disconnect recovery, or stream slice cleanup | `feature/stream-transcript-validation` | `python zhihuTTS_stream.py --reextract-retries ... --cleanup-slices` | Windows validation run |

If the task starts from local files in `Videos/`, use the MP4 branch. If the task starts from a web page, media URL, HLS/FLV stream, or browser-authenticated stream request, use the stream branch.

## Branch 1: local video transcript appendix

Branch:

```bash
feature/local-transcript-appendix
```

Purpose:

- Production-oriented branch for local MP4 files in `Videos/`.
- Keeps the existing `zhihuTTS.py` batch workflow.
- Adds a complete transcript appendix to each final Markdown output.
- Adds historical Markdown backfill commands.
- Uses SenseVoice/FunASR as the primary transcript backend for local MP4/backfill work.

Changed files relative to `main`:

```text
zhihuTTS.py
```

Use this branch when the task is:

- Process local video files from `Videos/`.
- Add `## 附录：完整逐字稿` to newly generated Markdown.
- Backfill complete transcript appendices into existing Markdown outputs.
- Replace old Whisper-generated appendices with SenseVoice/FunASR appendices.

Windows commands:

```bash
git fetch origin
git switch feature/local-transcript-appendix
git pull --ff-only
python zhihuTTS.py --backfill-transcripts
```

If transcript cache is missing but local videos are available:

```bash
python zhihuTTS.py --backfill-transcripts --transcribe-missing
```

If old Whisper appendices should be replaced:

```bash
python zhihuTTS.py --backfill-transcripts --transcribe-missing --force-transcribe --refresh-transcripts
```

More details:

```text
docs/SENSEVOICE_BACKFILL_RUNBOOK.md
docs/SENSEVOICE_MP4_BACKFILL_CHANGELOG_20260517.md
```

Do not use this branch for live stream or remote media URL validation.

## Branch 2: stream transcript validation

Branch:

```bash
feature/stream-transcript-validation
```

Purpose:

- Experimental branch for remote MP4/HLS/media URL validation.
- Does not change the production `zhihuTTS.py` local-video workflow.
- Adds a standalone stream validation runner.
- Supports URL slicing, auth headers, DevTools `Copy as cURL`, `yt-dlp`, Playwright page extraction, chunk transcript output, and manifest output.
- Uses SenseVoice/FunASR as the stream transcript backend.
- Supports URL re-extraction for expired signed URLs and disconnected streams when `--page-url` is available.
- Supports Playwright persistent session profiles for high-risk pages that depend on cookies, localStorage, and dynamic signatures.

Changed files relative to `main`:

```text
zhihuTTS_stream.py
```

Use this branch when the task is:

- Validate direct media URLs such as `.mp4`, `.m3u8`, `.mpd`, or `.flv`.
- Test auth headers or copied browser cURL requests.
- Test live room or replay page URL extraction.
- Test Playwright-based authenticated stream extraction for Zhihu or unknown/high-risk platforms.
- Test stream chunk recovery, manifest output, and optional slice cleanup.

Windows commands:

```bash
git fetch origin
git switch feature/stream-transcript-validation
git pull --ff-only
python zhihuTTS_stream.py --help
```

Example with a media URL:

```bash
python zhihuTTS_stream.py ^
  --url "https://example.com/live/index.m3u8" ^
  --duration 300 ^
  --chunk-duration 60 ^
  --name live-smoke ^
  --no-gemini
```

Example with DevTools `Copy as cURL`:

```bash
python zhihuTTS_stream.py ^
  --curl-file live-request.curl ^
  --duration 300 ^
  --chunk-duration 60 ^
  --name live-auth-smoke ^
  --no-gemini
```

Example with Playwright page extraction and session reuse:

```bash
python zhihuTTS_stream.py ^
  --page-url "https://www.zhihu.com/..." ^
  --extractor playwright ^
  --playwright-user-data-dir "Videos/.stream/playwright-zhihu-profile" ^
  --duration 1800 ^
  --chunk-duration 60 ^
  --stream-work-dir "Videos/.stream/chunks" ^
  --cleanup-slices ^
  --reextract-retries 3 ^
  --name live-cleanup-sensevoice ^
  --no-gemini
```

More details:

```text
docs/STREAM_SENSEVOICE_RUNBOOK.md
runs/windows-stream-replay-validation-20260517.md
```

Do not use this branch for normal production batch processing unless explicitly testing stream input.

## Main branch

Branch:

```bash
main
```

Purpose:

- Current production baseline.
- Contains the Windows production logs and Markdown outputs pushed on 2026-05-17.
- Does not yet include the complete transcript appendix code unless `feature/local-transcript-appendix` is merged.
- Does not include the stream validation runner unless `feature/stream-transcript-validation` is merged.

## Quick decision rule

Use:

```text
main
```

for stable production continuation without new transcript appendix behavior.

Use:

```text
feature/local-transcript-appendix
```

for local video production with complete transcript appendix output and historical backfill.

Use:

```text
feature/stream-transcript-validation
```

for remote/video-stream validation and future bilingual transcript experiments.

Avoid:

```text
stream-url-validation
```

This older branch mixed production evidence, local transcript changes, and stream validation work. Keep it as history only; do not use it as the merge base for production.
