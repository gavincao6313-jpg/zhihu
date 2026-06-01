# Stream SenseVoice Runbook

Date: 2026-05-17

## Purpose

This branch uses FunASR SenseVoice as the primary ASR backend for stream replay or media URL validation.

Use this branch for:

- Remote replay MP4 validation
- HLS/DASH/FLV/media URL validation
- DevTools `Copy as cURL` media request validation
- Future live-stream chunk transcription experiments

Do not use this branch for normal local MP4 batch production unless explicitly testing stream input.

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

Whisper-compatible fallback/testing:

```powershell
$env:TRANSCRIBE_BACKEND = "cpu"
$env:TRANSCRIBE_BACKEND = "whispercpp-vulkan"
```

## Install

Windows may reuse the already validated local SenseVoice virtual environment.

If installing from this branch:

```powershell
pip install -r requirements.txt
python -m playwright install chromium
```

If PyTorch/Torchaudio need manual CPU wheels, install them in the same virtual environment before running stream validation.

## Replay Stream Validation With SenseVoice

Use a local environment variable for signed URLs. Do not commit signed URLs or query secrets.

```powershell
git fetch origin
git switch feature/stream-transcript-validation
git pull --ff-only
$env:TRANSCRIBE_BACKEND = "sensevoice"
$env:REPLAY_URL = "<paste signed replay MP4 URL here>"

python zhihuTTS_stream.py `
  --url $env:REPLAY_URL `
  --start 0 `
  --duration 0 `
  --chunk-duration 300 `
  --name replay-full-sensevoice `
  --no-gemini
```

## Slice File Strategy

The stream runner slices media with ffmpeg into fixed-duration `.mp4` files before calling SenseVoice/FunASR. This is intentional for retry, recovery, Windows validation, and auditability.

Default behavior keeps slice files under `Videos/.stream/`:

```powershell
python zhihuTTS_stream.py `
  --url $env:REPLAY_URL `
  --duration 300 `
  --chunk-duration 60 `
  --name replay-slice-audit `
  --no-gemini
```

For long live validation where disk usage matters, choose a work directory and clean up each slice after transcript/report output has been written:

```powershell
python zhihuTTS_stream.py `
  --page-url "https://www.zhihu.com/..." `
  --extractor playwright `
  --playwright-user-data-dir "Videos/.stream/playwright-zhihu-profile" `
  --duration 1800 `
  --chunk-duration 60 `
  --stream-work-dir "Videos/.stream/chunks" `
  --cleanup-slices `
  --name live-cleanup-sensevoice `
  --no-gemini
```

The per-chunk report and manifest record the slice path, byte size, and whether the file was kept.

## Automatic Page URL Extraction

Use `--page-url` when you have a live room or replay page, not a direct media URL.

Auto routing:

- Known yt-dlp-friendly hosts use the yt-dlp extractor.
- Zhihu and unknown hosts use the Playwright network interceptor.
- Direct `--url` and `--curl-file` still bypass extraction and remain the debug fallback.

Example with yt-dlp cookies:

```powershell
$env:TRANSCRIBE_BACKEND = "sensevoice"
python zhihuTTS_stream.py `
  --page-url "https://live.bilibili.com/..." `
  --extractor auto `
  --ytdlp-cookies-browser chrome `
  --duration 300 `
  --chunk-duration 60 `
  --name live-ytdlp-sensevoice `
  --no-gemini
```

Example with Playwright storage state:

```powershell
$env:TRANSCRIBE_BACKEND = "sensevoice"
python zhihuTTS_stream.py `
  --page-url "https://www.zhihu.com/..." `
  --extractor playwright `
  --playwright-storage-state "Videos/.stream/storage_state.zhihu.json" `
  --duration 300 `
  --chunk-duration 60 `
  --name live-playwright-sensevoice `
  --no-gemini
```

For high-risk pages that depend on dynamic signatures or refreshed cookies, prefer a persistent Playwright profile. The profile directory is local runtime state and should not be committed.

For the first run, add `--playwright-headed` if the platform needs manual login or verification. Later runs can reuse the same profile directory in headless mode.

```powershell
$env:TRANSCRIBE_BACKEND = "sensevoice"
python zhihuTTS_stream.py `
  --page-url "https://www.zhihu.com/..." `
  --extractor playwright `
  --playwright-user-data-dir "Videos/.stream/playwright-zhihu-profile" `
  --duration 300 `
  --chunk-duration 60 `
  --name live-playwright-profile-sensevoice `
  --no-gemini
```

If you use a storage-state JSON instead of a persistent profile, write refreshed cookies/session data back after extraction:

```powershell
python zhihuTTS_stream.py `
  --page-url "https://www.zhihu.com/..." `
  --extractor playwright `
  --playwright-storage-state "Videos/.stream/storage_state.zhihu.json" `
  --playwright-save-storage-state "Videos/.stream/storage_state.zhihu.json" `
  --duration 300 `
  --chunk-duration 60 `
  --name live-playwright-state-refresh `
  --no-gemini
```

If the page needs debugging, add:

```powershell
--playwright-headed
```

## URL Expiration And Disconnect Recovery

When `--page-url` is used, the runner can recover from expired signed media URLs or dropped media connections at chunk boundaries.

Recovery behavior:

- ffmpeg first retries the same media URL internally with reconnect flags.
- If slicing still fails, the runner re-runs the configured extractor against `--page-url`.
- The refreshed stream URL and headers are probed, then the same failed chunk is retried.
- If extraction or probing fails temporarily, it consumes the same re-extraction retry budget and tries again.
- Recovery is recorded in the per-chunk report and manifest as `Stream re-extractions`.

Recommended live validation command:

```powershell
$env:TRANSCRIBE_BACKEND = "sensevoice"
python zhihuTTS_stream.py `
  --page-url "https://www.zhihu.com/..." `
  --extractor playwright `
  --playwright-storage-state "Videos/.stream/storage_state.zhihu.json" `
  --duration 300 `
  --chunk-duration 60 `
  --reextract-retries 3 `
  --reextract-delay-s 10 `
  --name live-recovery-sensevoice `
  --no-gemini
```

Limits:

- Automatic re-extraction requires `--page-url`; direct signed `--url` and `--curl-file` inputs have no upstream page to refresh from.
- Use a finite `--duration` for real live streams so validation has a controlled stop point.
- Re-extraction is only triggered by ffmpeg slicing failure. ASR failures still fail the chunk directly because refreshing the stream URL cannot fix model/runtime errors.

## Playwright Keepalive Mode

Use keepalive mode for Zhihu live validation when the browser page may need to stay open for page heartbeat, refreshed cookies, or dynamic media signatures.

Behavior:

- Opens one Playwright persistent context/page for the whole run.
- Keeps listening for media requests while ffmpeg slices chunks.
- Uses the best latest intercepted media URL before each chunk.
- On ffmpeg slicing failure, refreshes the existing page and waits for a fresh media request before retrying.
- Closes the browser only after the validation run exits.

Recommended two-hour Zhihu live command:

```powershell
$env:TRANSCRIBE_BACKEND = "sensevoice"
python zhihuTTS_stream.py `
  --page-url "https://www.zhihu.com/..." `
  --extractor playwright `
  --playwright-user-data-dir "Videos/.stream/playwright-zhihu-profile" `
  --playwright-keepalive `
  --playwright-headed `
  --duration 7200 `
  --chunk-duration 60 `
  --stream-work-dir "Videos/.stream/chunks" `
  --cleanup-slices `
  --reextract-retries 3 `
  --reextract-delay-s 10 `
  --keepalive-refresh-wait-s 10 `
  --name zhihu-live-keepalive-sensevoice `
  --no-gemini
```

After the profile has a stable login session, remove `--playwright-headed` for unattended validation. Keep `--playwright-user-data-dir` so cookies and localStorage are reused.

## Authenticated Media Request

For media requests requiring headers:

```powershell
$env:TRANSCRIBE_BACKEND = "sensevoice"
python zhihuTTS_stream.py `
  --curl-file live-request.curl `
  --duration 300 `
  --chunk-duration 60 `
  --name live-auth-sensevoice `
  --no-gemini
```

## Notes

- `zhihuTTS_stream.py` still handles URL slicing, retries, and manifest generation.
- `zhihuTTS_video.transcribe_audio()` owns the ASR backend selection.
- Output remains compatible with the existing transcript shape: `segments[{start,end,text,words}]`.
- Product and technical terms are normalized after ASR, including Cursor, Claude Code, MiniMax Agent, RAG, MCP, CLI, API, web coding, and AI coding.
- Reports record only header names, not header values.
