# Cerebrum

> OpenWolf's learning memory. Updated automatically as the AI learns from interactions.
> Do not edit manually unless correcting an error.
> Last updated: 2026-05-14

## User Preferences

<!-- How the user likes things done. Code style, tools, patterns, communication. -->
- **Windows Run Owner role:** User explicitly limits this side to running scripts, analyzing logs, committing `.progress.json`, Markdown outputs, and run reports; do not modify `.py`, `requirements.txt`, `githooks`, or architecture code.
- **Shared context files:** Commit and push repo-level coordination files that Mac and Windows both need to read, including `AGENTS.md`, `CLAUDE.md`, `.claude/settings.json`, and `.claude/rules/openwolf.md`.
- **Local-only config:** Keep `.claude/settings.local.json` out of Git; it is machine-specific permission state and should stay local.
- **Stream validation workflow:** User wants to validate video-stream handling step by step by first running one complete replay stream end-to-end before attempting real live stream input.
- **Mac/Windows stream validation split:** User decided Mac hardware should not run the complete replay-stream validation; write Windows-facing handoff instructions and let Windows perform the long run.

## Key Learnings

- **Project:** zhihu
- **Project pipeline:** zhihu processes local videos from `Videos/` into detailed NotebookLM-ready Markdown using `zhihuTTS.py` orchestration, `zhihuTTS_video.py` ffmpeg keyframe extraction + Whisper transcription, then a Gemini 2.5 Flash multimodal call with auto-continuation.
- **Collaboration rule:** Windows side is runner-only and should not change `.py`; Mac side owns code changes. Windows commits only `.progress.json`/run outputs according to `COLLABORATION.md`.
- **Current scale:** As of 2026-05-16 review, `Videos/` has 63 video files; `.progress.json` marks 31 matching files done and 32 pending, with 2 API quota units used on 2026-05-16.
- **Operational gotcha:** PowerShell profile loading emits an execution-policy error on each shell command; use `powershell -NoProfile` or fix/remove the profile to keep logs clean.
- **Stream validation route:** Video stream/live URL work is isolated on `feature/stream-transcript-validation`; `main` intentionally lacks `zhihuTTS_stream.py`, and validation needs a real media URL or DevTools `Copy as cURL` input.
- **Replay stream runner behavior:** On `feature/stream-transcript-validation`, `zhihuTTS_stream.py --duration 0` processes from `--start` to probed source end; `--chunk-duration` controls slice size; the script never calls Gemini and produces per-chunk reports plus combined transcript and manifest under `runs/`.
- **Replay probe 2026-05-17:** The tested signed replay MP4 from `vdn6.vzuu.com` was ffprobe-readable with duration about `02:42:53`, H.264 1080p video, AAC 44.1k stereo audio, and size about 309 MB.

## Do-Not-Repeat

<!-- Mistakes made and corrected. Each entry prevents the same mistake recurring. -->
<!-- Format: [YYYY-MM-DD] Description of what went wrong and what to do instead. -->

## Decision Log

<!-- Significant technical decisions with rationale. Why X was chosen over Y. -->
