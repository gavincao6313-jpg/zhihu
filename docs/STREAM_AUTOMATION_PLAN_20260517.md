# Stream Automation Plan - 2026-05-17

## Current State

- Complete replay-stream validation has been handed off to the Windows user.
- Mac already verified the supplied replay MP4 URL with `ffprobe`.
- Mac should not run the complete replay validation because local hardware is not suitable for the multi-hour Whisper workload.
- Windows has pulled the latest Git changes and started the validation task.
- Handoff file: `runs/windows-stream-replay-validation-20260517.md`

## Replay Validation Scope

The Windows replay validation is intended to prove the existing stream runner can process one complete remote replay source end to end:

1. Probe the remote media URL.
2. Slice the remote MP4 into chunks.
3. Extract keyframes.
4. Run Whisper transcription.
5. Offset chunk timestamps to source-video time.
6. Produce per-chunk reports.
7. Produce combined transcript and manifest.

The stream runner does not call Gemini.

## Live Stream Problem Statement

Replay MP4 validation proves the processing pipeline. It does not solve real live-stream acquisition.

The remaining live-stream blockers are:

- A room/page URL is often HTML, not the actual media stream.
- The actual stream may require browser auth context such as `Cookie`, `Authorization`, `Referer`, `Origin`, and `User-Agent`.
- Real live input may be HLS `.m3u8`, DASH `.mpd`, FLV, RTMP, RTSP, WebRTC, or a platform-specific transport.
- Signed URLs can expire during long runs.
- WebRTC may not expose a single ffmpeg-readable URL.
- CPU Whisper is still the throughput bottleneck unless Windows/GPU/whisper.cpp is used.
- Long-running live processing needs retry, reconnection, and checkpoint semantics.

## Automation Direction

Manual DevTools capture should be replaced by a Python stream-extractor layer upstream of `zhihuTTS_stream.py`.

Proposed architecture:

```text
Room/page URL
  -> stream_extractors.py
      -> yt-dlp extractor
      -> Playwright network extractor
      -> direct URL / curl-file fallback
  -> ExtractedStream(url, headers, extractor, media_type, expires_at)
  -> zhihuTTS_stream.py
  -> ffmpeg slice
  -> Whisper transcript
  -> manifest / combined transcript
```

## Proposed Python API

```python
from dataclasses import dataclass

@dataclass
class ExtractedStream:
    url: str
    headers: dict[str, str]
    extractor: str
    media_type: str
    page_url: str
    expires_at: str | None = None
```

Candidate file split:

```text
stream_extractors.py
zhihuTTS_stream.py
stream_supervisor.py
```

`zhihuTTS_stream.py` should consume an `ExtractedStream` and avoid knowing whether the stream came from yt-dlp, Playwright, direct URL, or cURL.

## Extractor Priority

First implementation should support `--page-url` and `--extractor auto`.

Recommended order:

1. Use direct `--url` if provided.
2. Use existing `--curl-file` if provided.
3. Try `yt-dlp` for `--page-url`.
4. Fall back to Playwright network interception.

Example future command:

```bash
python zhihuTTS_stream.py \
  --page-url "https://www.zhihu.com/..." \
  --extractor auto \
  --start 0 \
  --duration 0 \
  --chunk-duration 300 \
  --name live-auto \
  --no-gemini
```

## Playwright Extractor Notes

Playwright should automate what was previously done manually in DevTools:

- Open the room/page URL.
- Reuse logged-in browser state or load a local cookie/storage file.
- Listen to network requests and responses.
- Match media candidates such as `.m3u8`, `.flv`, `.mpd`, `vzuu.com`, or known live API patterns.
- Capture request URL and request headers.
- Close the browser after a valid candidate is found.

## yt-dlp Extractor Notes

`yt-dlp` should be tried first because it is lightweight and may already know platform extraction rules.

Expected limitations:

- It may not support the target Zhihu live page.
- It may fail on auth-protected pages.
- It may need browser cookies, for example Chrome cookies.

## Supervisor Is Phase Two

Do not start by building the full watchdog/supervisor.

Phase one should prove:

```text
page URL -> automatic extraction -> one validation run
```

Phase two should add:

- ffmpeg process monitoring
- 403/404/timeout/EOF detection
- URL re-extraction
- chunk-level checkpointing
- resume from the next chunk
- manifest entries for failed/retried chunks

## Security Rules

- Do not commit signed URLs.
- Do not commit `pkey`, `Cookie`, or `Authorization` values.
- Reports should list header names only.
- Store local secret inputs under ignored paths such as `Videos/.stream/requests/`.
- Redact URLs in long-lived manifests; host and media type are usually enough.

## Resume Point

When quota/session capacity resumes, continue from:

1. Check Windows replay validation result.
2. If replay validation passed, implement `stream_extractors.py`.
3. Add `--page-url` and `--extractor auto` to `zhihuTTS_stream.py`.
4. Start with `yt-dlp`, then Playwright fallback.
5. Keep `--curl-file` as the manual debug fallback.
