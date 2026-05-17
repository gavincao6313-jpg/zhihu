# Windows SenseVoice Stream Validation - 2026-05-17

## Summary

Windows validated the current stream replay runner and probed Alibaba FunASR SenseVoice as a replacement candidate for Whisper transcription.

Result:

- Stream replay pipeline with Whisper-compatible flow: completed after adding retry protection around remote slicing.
- SenseVoice as an audio transcription model: viable for Chinese transcript output, but not yet fully integrated into the stream runner.
- Engineering status: SenseVoice should be added as an optional backend first, with Whisper retained as fallback.

## Branch And Scope

- Branch: `feature/stream-transcript-validation`
- Stream entrypoint: `zhihuTTS_stream.py`
- Probe script: `sensevoice_probe.py`
- No Gemini calls were made during stream replay validation.
- No signed replay URL, query secret, cookie, or auth header is recorded in this report.

## Stream Replay Validation

Source media, after redaction:

- Host: `vdn6.vzuu.com`
- Container: MP4 / QuickTime MOV
- Duration: `02:42:53`
- Size: `309342920` bytes
- Video: H.264, `1920x1080`, about `15 fps`
- Audio: AAC HE-AAC, `44100 Hz`, stereo

Final successful run:

- Chunks: `33`
- Chunk duration: `300s`, except final chunk `173s`
- Backend: faster-whisper CPU
- Processing elapsed sum: `1996.22s`
- Transcript segments: `3682`
- Transcript chars: `126350`
- Kept frames: `485`
- Final combined transcript: `runs/stream-replay-full-20260517-112146.combined-transcript.txt`
- Final manifest JSON: `runs/stream-replay-full-20260517-112146.manifest.json`

## Stream Failure Observed

Before the successful run, remote slicing failed twice with transient TLS / HTTP proxy I/O errors:

- First failure: chunk 3 at `00:10:00`
- Second failure: chunk 2 at `00:05:00`
- One failed attempt produced an empty MP4 slice, which caused downstream keyframe extraction to fail.

Code change made for validation:

- Added ffmpeg reconnect options in `slice_url()`.
- Added `SLICE_RETRIES = 3`.
- Added minimum slice size validation.
- Captured ffmpeg output and redacted the URL from thrown errors.

This was necessary for the replay validation to finish reliably enough for Windows-side testing.

## SenseVoice Probe Environment

Installed into local, ignored virtual environment:

- Python: `3.12`
- Virtual env: `.venv-sensevoice`
- `funasr==1.3.1`
- `modelscope==1.37.0`
- `torch==2.12.0+cpu`
- `torchaudio==2.11.0+cpu`

Models:

- ASR: `iic/SenseVoiceSmall`
- VAD: `fsmn-vad`
- Model cache: `cache/modelscope/hub`

The model cache is local-only and ignored by Git.

## SenseVoice Samples

Three short audio samples were cut from the replay chunks and transcribed with SenseVoice.

| Sample | Source chunk | Offset | Duration | Output |
|---|---:|---:|---:|---|
| `sensevoice-chunk028-90s.wav` | 28 | `00:01:30` | 90s | `runs/sensevoice-chunk028-90s-sensevoice-chunk028-90s-20260517-153052.txt` |
| `sensevoice-chunk029-80s.wav` | 29 | `00:03:00` | 80s | `runs/sensevoice-chunk029-80s-sensevoice-chunk029-80s-20260517-153250.txt` |
| `sensevoice-chunk030-80s.wav` | 30 | `00:02:10` | 80s | `runs/sensevoice-chunk030-80s-sensevoice-chunk030-80s-20260517-153322.txt` |

The `.wav` files are local probe media and should not be committed.

## SenseVoice Findings

What improved compared with the observed Whisper output:

- SenseVoice output was Simplified Chinese in all three samples.
- Punctuation and readability were better for Chinese lecture text.
- Some English technical terms were preserved better, including `API`, `MCP`, `computer`, `web coding`, `AI coding`, and `CLI`.
- CPU inference was fast after model download: roughly `4.6s` to `5.2s` for `80s` to `90s` audio samples, with reported RTF around `0.058`.

Remaining issues:

- Proper nouns still need correction:
  - `Cursor` / `Claude Code`-like terms appeared as `叉code`, `cloud code`, `克拉 code`, or `cloud coldword`.
  - `MiniMax Agent` appeared as `mini max agent`.
  - `RAG` appeared as lowercase `rag`.
- SenseVoice's default output does not match the existing transcript shape with `segments[{start,end,text,words}]`.
- Full 33-chunk stream replay has not yet been rerun with SenseVoice integrated as the backend.

## Engineering Recommendation For Mac

Add SenseVoice as an optional transcription backend, not as an immediate destructive replacement.

Suggested direction:

1. Add a backend switch such as `TRANSCRIBE_BACKEND=sensevoice`, or extend the existing backend switch to accept `sensevoice`.
2. Keep faster-whisper / whisper.cpp as fallback until SenseVoice has full stream-runner validation.
3. Convert SenseVoice VAD pieces into the existing transcript shape with global chunk offsets.
4. Add post-processing after every backend:
   - Simplified Chinese normalization.
   - Domain glossary normalization for terms such as `Cursor`, `Claude Code`, `MiniMax Agent`, `RAG`, `MCP`, `CLI`, `API`, and `web coding`.
5. Run the same 33-chunk replay MP4 end to end with SenseVoice before promoting it to default.

## Risk List

Scenarios that may still make the stream pipeline unavailable:

- Source is not a seekable replay MP4, for example true HLS, DASH, FLV, RTMP, RTSP, or WebRTC.
- Signed URL expires or requires auth headers not captured by ffmpeg.
- Remote proxy/TLS stream interrupts repeatedly beyond retry budget.
- SenseVoice model cache is unavailable, incomplete, or not writable.
- Python/PyTorch/FunASR dependency setup differs across Windows and Mac.
- Timestamp mapping is missing or inaccurate after replacing Whisper.
- Product names and English technical terms are not normalized after ASR.
