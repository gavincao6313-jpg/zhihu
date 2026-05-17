# Branch Usage Guide

Date: 2026-05-17

This repository currently has two feature branches with different purposes. Do not mix them during Windows production runs.

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

Changed files relative to `main`:

```text
zhihuTTS.py
```

Use this branch when the task is:

- Process local video files from `Videos/`.
- Add `## 附录：完整逐字稿` to newly generated Markdown.
- Backfill complete transcript appendices into existing Markdown outputs.

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
- Supports URL slicing, auth headers, DevTools `Copy as cURL`, chunk transcript output, and manifest output.

Changed files relative to `main`:

```text
zhihuTTS_stream.py
```

Use this branch when the task is:

- Validate direct media URLs such as `.mp4`, `.m3u8`, `.mpd`, or `.flv`.
- Test auth headers or copied browser cURL requests.
- Prepare future stream features such as English transcript plus Chinese translation.

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
