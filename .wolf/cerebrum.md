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
- **Quota/session preservation:** When user says the 5-hour quota is about to run out, immediately write discussion results into repo docs and OpenWolf memory so work can resume after quota recovery.

## Key Learnings

- **Project:** zhihu
- **Project pipeline:** zhihu processes local videos from `Videos/` into detailed NotebookLM-ready Markdown using `zhihuTTS.py` orchestration, `zhihuTTS_video.py` ffmpeg keyframe extraction + Whisper transcription, then a Gemini 2.5 Flash multimodal call with auto-continuation.
- **Collaboration rule:** Windows side is runner-only and should not change `.py`; Mac side owns code changes. Windows commits only `.progress.json`/run outputs according to `COLLABORATION.md`.
- **Current scale:** As of 2026-05-16 review, `Videos/` has 63 video files; `.progress.json` marks 31 matching files done and 32 pending, with 2 API quota units used on 2026-05-16.
- **Operational gotcha:** PowerShell profile loading emits an execution-policy error on each shell command; use `powershell -NoProfile` or fix/remove the profile to keep logs clean.
- **Stream validation route:** Video stream/live URL work is isolated on `feature/stream-transcript-validation`; `main` intentionally lacks `zhihuTTS_stream.py`, and validation needs a real media URL or DevTools `Copy as cURL` input.
- **Replay stream runner behavior:** On `feature/stream-transcript-validation`, `zhihuTTS_stream.py --duration 0` processes from `--start` to probed source end; `--chunk-duration` controls slice size; the script never calls Gemini and produces per-chunk reports plus combined transcript and manifest under `runs/`.
- **Replay probe 2026-05-17:** The tested signed replay MP4 from `vdn6.vzuu.com` was ffprobe-readable with duration about `02:42:53`, H.264 1080p video, AAC 44.1k stereo audio, and size about 309 MB.
- **Stream automation plan:** Replace manual DevTools URL capture with a Python extractor layer upstream of `zhihuTTS_stream.py`; implement `stream_extractors.py` with direct URL/curl-file fallback, `yt-dlp`, then Playwright network interception, and defer watchdog/supervisor behavior until extraction-to-run works once.
- **Live mode design decisions (2026-05-18):** `--duration 0` = run until stream ends; browser auto-restarts max 3 times (`MAX_BROWSER_RESTARTS`), then prints manual-intervention message; Playwright mode polls DOM via `is_stream_ended()` checking `STREAM_ENDED_TEXTS`; yt-dlp mode checks `is_ytdlp_stream_ended_error()` on extract failure; clean exit via `StreamEndedError`; browser dead raises `BrowserDeadError` caught in `run_validation`.
- **Replay validation result:** Windows completed the full 33-chunk replay-stream validation on `origin/feature/stream-transcript-validation`; manifest reports 02:42:53 covered, 1996.22s processing elapsed sum, 3682 segments, 126350 transcript chars, and 485 kept frames.
- **SenseVoice direction:** Windows found Whisper transcript quality insufficient and validated FunASR SenseVoiceSmall as a credible Chinese ASR candidate; add it as an optional backend first, keep Whisper/faster-whisper fallback, and normalize domain terms such as Cursor, Claude Code, MiniMax Agent, RAG, MCP, CLI, API.
- **ASR scope expansion:** Because local MP4 processing and stream chunks both call `zhihuTTS_video.transcribe_audio()`, SenseVoice should be implemented as a shared transcription backend for both stream replay/live chunks and remaining local MP4 transcript backfill work.
- **MP4 SenseVoice push:** Pushed `1d611f6 feat: use SenseVoice for transcript backfill` to `feature/local-transcript-appendix`; it makes SenseVoice the default `TRANSCRIBE_BACKEND`, adds cache backend mismatch handling, `--force-transcribe`, `--refresh-transcripts`, glossary normalization, and Windows runbook docs.
- **Windows stream hardening code:** Windows later pushed commit `5371c70` on `origin/feature/stream-transcript-validation`, adding `sensevoice_probe.py`, `.gitignore` entries for `.venv*/runs/*.wav`, and `zhihuTTS_stream.py` hardening with ffmpeg reconnect, `SLICE_RETRIES = 3`, `MIN_SLICE_BYTES = 1024`, retry delay, and redacted slice errors.
- **Zhihu live stream architecture (2026-05-18):** Zhihu uses CC (csslcloud.net) as streaming backend. FLV URL via `view.csslcloud.net/api/live/play?types=flv`, auth_key ~8h TTL. Anti-detection required: `--disable-blink-features=AutomationControlled` + `add_init_script` hiding `navigator.webdriver`. Plain Playwright returns 403. Login via `login_save_auth.py` (QR scan), saves `zhihu_auth_state.json` (gitignored). Working command uses `--playwright-keepalive --page-url <live_url> --gemini`.
- **Mac env for stream validation (2026-05-18):** Python 3.11 (x86_64) at `~/.local/bin/python3.11`. Venv at `/private/tmp/zhihu-stream-validation/.venv-mac311`. funasr blocked by llvmlite/numba → LLVM build chain; workaround: use `TRANSCRIBE_BACKEND=faster-whisper` for Mac tests, SenseVoice runs on Windows. Playwright chromium installed to `.playwright-browsers/`. Must set `PLAYWRIGHT_BROWSERS_PATH=/private/tmp/zhihu-stream-validation/.playwright-browsers` when running scripts.
- **Live-mode optimization batch (2026-05-18):** 4 items applied from Windows code audit `0755f87`: (1) `transcribe_audio()` called before `extract_keyframes()` — silent chunks return None, slice deleted; (2) incremental checkpoint JSON after each real chunk (`stream-{base}.checkpoint.json`), deleted on clean exit; (3) `MAX_BROWSER_RESTARTS` exposed as `--max-browser-restarts` CLI arg (default 3); (4) `close()` wraps each Playwright resource in independent try/except; `restart()` clears state in `finally`. P2 pipeline parallelism and checkpoint/resume deferred.

## Do-Not-Repeat

<!-- Mistakes made and corrected. Each entry prevents the same mistake recurring. -->
<!-- Format: [YYYY-MM-DD] Description of what went wrong and what to do instead. -->

## Decision Log

<!-- Significant technical decisions with rationale. Why X was chosen over Y. -->
