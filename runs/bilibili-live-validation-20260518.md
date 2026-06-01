# Bilibili Live Stream Validation - 2026-05-18

## Summary

Windows validated the full stream pipeline against a real bilibili.com live room: yt-dlp extraction → ffmpeg slicing → SenseVoice transcription. 28 of 30 chunks completed successfully before a no-speech chunk exposed a missing edge case in the transcription path.

Result: the stream pipeline works end-to-end for bilibili live. Two bugs need Mac-side code fixes.

## Branch And Scope

- Branch: `feature/stream-transcript-validation`
- No Gemini calls were made (--no-gemini).
- No signed URL, query secret, cookie, or auth header is recorded in this report.

## Source

- Page URL: `https://live.bilibili.com/8178490` (session params redacted from report)
- Extractor: yt-dlp (HLS) — auto-routed correctly for live.bilibili.com
- Container: MP4 / QuickTime MOV (ffmpeg-remuxed from HLS)
- Video: H.265 HEVC, 1920×1080, 25 fps
- Audio: AAC LC, 48000 Hz, stereo
- Duration requested: 30 minutes (1800s)
- Chunk duration: 60s (30 planned chunks)

## Validation Run

- Chunks completed: **28 / 30**
- Chunk MP4 slices: 29 files, **192 MB** total (under `Videos/.stream/`)
- Transcript output: **19,824 characters** Simplified Chinese
- Total processing wall time: ~55 minutes
- ASR backend: SenseVoice (iic/SenseVoiceSmall + fsmn-vad, cpu)
- Average RTF: ~0.07 (very fast)

## Chunk Summary

All 28 completed chunks produced clean Simplified Chinese transcripts with good punctuation. Content observed:

- Social/legal documentary narration (Civil Code cases, fraud stories, drunk-driving scams)
- Commercial/promo interstitials (小鹏 GX, 金石探文明 CCTV program)
- SenseVoice `🎼` music-detection markers present on chunks with background music

## Failure: Chunk 29 (00:28:00–00:29:00)

```
RuntimeError: SenseVoice 未返回有效转写文本
  at zhihuTTS_video.py:318 (_transcribe_sensevoice)
```

### Root Cause

The live stream at 00:28:00 entered a music-only or silence segment (interstitial break between content). SenseVoice VAD correctly identified zero speech segments and returned an empty list. `_transcribe_sensevoice()` treats this as a hard error (raise RuntimeError), which aborted the entire run.

ffprobe confirms chunk 29 has valid AAC audio (48kHz stereo, 60s duration, 128 kbps). The audio is present — it just contains no detectable speech.

### Recommended Fix (Mac / Code Owner)

`zhihuTTS_video.py`, `_transcribe_sensevoice()`, around line 317:

```python
# BEFORE (current — crashes the run on no-speech chunks):
if not segments:
    raise RuntimeError("SenseVoice 未返回有效转写文本")

# AFTER (proposed — skip with empty transcript):
if not segments:
    print("  [SenseVoice] 无语音，跳过此切片", flush=True)
    return {
        "segments": [],
        "sensevoice": {
            "model": SENSEVOICE_MODEL,
            "vad_model": SENSEVOICE_VAD_MODEL,
            "device": device,
            "duration_s": duration_s,
        },
    }
```

The caller (`zhihuTTS_stream.py` `process_slice()`) should also handle empty segments gracefully — write the report with `speech_detected: false` and `segment_count: 0` rather than erroring.

## Playwright Extraction Test

A separate 10s test with `--extractor playwright` on the same bilibili URL confirmed:

```
RuntimeError: Playwright 未拦截到 .m3u8/.mpd/.flv/.mp4 媒体请求
```

Bilibili's live player loads inside a cross-origin iframe or uses MSE (Media Source Extensions), so Playwright's network interception sees no direct media requests. This confirms the auto-routing logic is correct: bilibili → yt-dlp, zhihu → Playwright.

No code change needed for this; just a confirmed design decision.

## Dependency Status

Installed into `.venv-sensevoice` during this session:

| Package | Before | After |
|---|---|---|
| yt-dlp | missing | 2026.3.17 |
| playwright | missing | 1.59.0 + Chromium 147 |
| funasr | 1.3.1 | (unchanged) |

## New Bugs For Handoff

### bug-019: SenseVoice empty transcript crashes the run

- **File**: `zhihuTTS_video.py:318` (`_transcribe_sensevoice`)
- **Severity**: Medium — aborts multi-chunk runs on any silent/music-only chunk
- **Repro**: Run against any live stream that has a music-only or silent intermission
- **Expected**: Skip the chunk with `speech_detected: false`, continue to next chunk

### bug-020: Playwright extractor fails on bilibili

- **File**: `stream_extractors.py` (design limitation, not a code defect)
- **Severity**: Low — auto-routing correctly avoids Playwright for bilibili
- **Confirmed**: `--extractor auto` routes `live.bilibili.com` to yt-dlp, which is correct. No action needed beyond documenting the limitation.

## Artifacts Committed

- `runs/bilibili-live-validation-20260518.md` — this report
- `runs/stream-bilibili-live-30min_chunk*/` — 28 chunk reports (`.md` + `.transcript.txt` + `.global-transcript.txt` + `.payload.json`)
- `.wolf/buglog.json` — bugs 019, 020 appended
- `.wolf/memory.md` — session actions appended
