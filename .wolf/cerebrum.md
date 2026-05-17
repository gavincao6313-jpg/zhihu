# Cerebrum

> OpenWolf's learning memory. Updated automatically as the AI learns from interactions.
> Do not edit manually unless correcting an error.
> Last updated: 2026-05-14

## User Preferences

<!-- How the user likes things done. Code style, tools, patterns, communication. -->
- **Windows Run Owner role:** User explicitly limits this side to running scripts, analyzing logs, committing `.progress.json`, Markdown outputs, and run reports; do not modify `.py`, `requirements.txt`, `githooks`, or architecture code.

## Key Learnings

- **Project:** zhihu
- **Project pipeline:** zhihu processes local videos from `Videos/` into detailed NotebookLM-ready Markdown using `zhihuTTS.py` orchestration, `zhihuTTS_video.py` ffmpeg keyframe extraction + Whisper transcription, then a Gemini 2.5 Flash multimodal call with auto-continuation.
- **Collaboration rule:** Windows side is runner-only and should not change `.py`; Mac side owns code changes. Windows commits only `.progress.json`/run outputs according to `COLLABORATION.md`.
- **Current scale:** As of 2026-05-16 review, `Videos/` has 63 video files; `.progress.json` marks 31 matching files done and 32 pending, with 2 API quota units used on 2026-05-16.
- **Operational gotcha:** PowerShell profile loading emits an execution-policy error on each shell command; use `powershell -NoProfile` or fix/remove the profile to keep logs clean.
- **Stream SenseVoice backend:** On `feature/stream-transcript-validation`, stream chunks should use the shared `zhihuTTS_video.transcribe_audio()` backend with `TRANSCRIBE_BACKEND=sensevoice` by default; `zhihuTTS_stream.py` remains responsible for slicing/retry/manifest only.
- **Stream URL extraction:** `stream_extractors.py` is the upstream extractor layer for page URLs; `--page-url --extractor auto` routes known hosts through yt-dlp and Zhihu/unknown hosts through Playwright network interception while keeping `--url` and `--curl-file` as fallback inputs.
- **Stream URL recovery:** URL expiration/disconnect recovery is chunk-scoped: ffmpeg retries the current media URL first, then `zhihuTTS_stream.py` only re-runs the page extractor for `StreamSliceError` when `--page-url` is available; ASR/runtime errors should not trigger URL re-extraction.
- **Playwright high-risk platform path:** Treat Playwright_Flow as the preferred path for Zhihu/unknown/high-risk pages because a real browser session can preserve cookies/localStorage and run dynamic signing JavaScript; use a persistent profile or write back storage_state rather than relying on one-off manual URL capture.
- **Stream slice storage:** Stream validation intentionally slices to fixed-duration MP4 files before SenseVoice/FunASR; keep slices by default for audit/retry, but long live runs can use `--cleanup-slices` after transcript/report output to control disk use.

## Do-Not-Repeat

<!-- Mistakes made and corrected. Each entry prevents the same mistake recurring. -->
<!-- Format: [YYYY-MM-DD] Description of what went wrong and what to do instead. -->

## Decision Log

<!-- Significant technical decisions with rationale. Why X was chosen over Y. -->
- **2026-05-17 Stream recovery scope:** Implement recovery inside the existing chunk loop instead of a full outer supervisor first, because validation needs to survive expired signed URLs and dropped connections during a finite replay/live run while preserving chunk reports and SenseVoice output shape.
- **2026-05-17 Playwright session strategy:** For platforms with stronger risk controls, prioritize persistent Playwright sessions over static signed URLs because the page can refresh cookies and dynamic signatures before every extraction/re-extraction.
- **2026-05-18 Slice retention strategy:** Keep file-based chunking as the main path instead of in-memory Bytes because Windows validation needs reproducible artifacts, while adding cleanup controls for long live sessions.
