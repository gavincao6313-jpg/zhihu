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

If the page needs debugging, add:

```powershell
--playwright-headed
```

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
