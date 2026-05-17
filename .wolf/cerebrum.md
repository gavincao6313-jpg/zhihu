# Cerebrum

> OpenWolf's learning memory. Updated automatically as the AI learns from interactions.
> Do not edit manually unless correcting an error.
> Last updated: 2026-05-14

## User Preferences

<!-- How the user likes things done. Code style, tools, patterns, communication. -->
- **Windows Run Owner role:** User explicitly limits this side to running scripts, analyzing logs, committing `.progress.json`, Markdown outputs, and run reports; do not modify `.py`, `requirements.txt`, `githooks`, or architecture code.
- **Shared context files:** Commit and push repo-level coordination files that Mac and Windows both need to read, including `AGENTS.md`, `CLAUDE.md`, `.claude/settings.json`, and `.claude/rules/openwolf.md`.
- **Local-only config:** Keep `.claude/settings.local.json` out of Git; it is machine-specific permission state and should stay local.

## Key Learnings

- **Project:** zhihu
- **Project pipeline:** zhihu processes local videos from `Videos/` into detailed NotebookLM-ready Markdown using `zhihuTTS.py` orchestration, `zhihuTTS_video.py` ffmpeg keyframe extraction + Whisper transcription, then a Gemini 2.5 Flash multimodal call with auto-continuation.
- **Collaboration rule:** Windows side is runner-only and should not change `.py`; Mac side owns code changes. Windows commits only `.progress.json`/run outputs according to `COLLABORATION.md`.
- **Current scale:** As of 2026-05-16 review, `Videos/` has 63 video files; `.progress.json` marks 31 matching files done and 32 pending, with 2 API quota units used on 2026-05-16.
- **Operational gotcha:** PowerShell profile loading emits an execution-policy error on each shell command; use `powershell -NoProfile` or fix/remove the profile to keep logs clean.

## Do-Not-Repeat

<!-- Mistakes made and corrected. Each entry prevents the same mistake recurring. -->
<!-- Format: [YYYY-MM-DD] Description of what went wrong and what to do instead. -->

## Decision Log

<!-- Significant technical decisions with rationale. Why X was chosen over Y. -->
