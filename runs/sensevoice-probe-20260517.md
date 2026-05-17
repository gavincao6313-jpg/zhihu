# SenseVoice Probe - 2026-05-17

## Goal

Evaluate whether Alibaba FunASR SenseVoice improves Chinese-dominant lecture transcription with embedded English technical terms, and whether it avoids mixed Simplified/Traditional Chinese output seen in the Whisper run.

## Environment

- Python: `3.12` in `.venv-sensevoice`
- Packages: `funasr==1.3.1`, `modelscope==1.37.0`, `torch==2.12.0+cpu`, `torchaudio==2.11.0+cpu`
- Model: `iic/SenseVoiceSmall`
- VAD: `fsmn-vad`
- Device: `cpu`
- Model cache: `cache/modelscope/hub`
- Probe script: `sensevoice_probe.py`

## Samples

| Sample | Source chunk | Offset | Duration | Output |
|---|---:|---:|---:|---|
| `sensevoice-chunk028-90s.wav` | 28 | `00:01:30` | 90s | `runs/sensevoice-chunk028-90s-sensevoice-chunk028-90s-20260517-153052.txt` |
| `sensevoice-chunk029-80s.wav` | 29 | `00:03:00` | 80s | `runs/sensevoice-chunk029-80s-sensevoice-chunk029-80s-20260517-153250.txt` |
| `sensevoice-chunk030-80s.wav` | 30 | `00:02:10` | 80s | `runs/sensevoice-chunk030-80s-sensevoice-chunk030-80s-20260517-153322.txt` |

## Findings

- SenseVoice output was Simplified Chinese in all three samples.
- English technical terms improved in some cases: `API`, `MCP`, `computer`, `web coding`, `AI coding`, and `CLI` were preserved or partially preserved.
- It still misrecognized some proper nouns and product names:
  - `Cursor`/`Claude Code`-like terms were rendered as `叉code`, `cloud code`, `克拉 code`, `cloud coldword`.
  - `MiniMax Agent` was rendered as `mini max agent`, acceptable but needs normalization.
  - `RAG` was rendered as lowercase `rag`, acceptable if post-processed.
- SenseVoice generated cleaner punctuation and paragraph text than the current Whisper segment text.
- The default FunASR/SenseVoice output does not include timestamped segments in the same shape as the existing Whisper pipeline. For production replacement, timestamps need to come from VAD chunk offsets or a separate timestamping strategy.

## Performance

After the initial model download, CPU inference was fast on short probes:

- 90s sample: about 5.2s inference after model load
- 80s samples: about 4.6s inference after model load
- Reported RTF was about `0.058`

## Recommendation

SenseVoice is worth adding as an optional backend for Chinese lecture transcription, especially to enforce Simplified Chinese and improve punctuation. It should not replace Whisper blindly until timestamp handling and proper-noun normalization are added.

Suggested next step:

1. Add `WHISPER_BACKEND=sensevoice` or a new `TRANSCRIBE_BACKEND=sensevoice` path.
2. Convert SenseVoice VAD pieces into the existing transcript shape: `segments[{start,end,text,words}]`.
3. Add a domain glossary normalization pass for terms such as `Cursor`, `Claude Code`, `MiniMax Agent`, `RAG`, `MCP`, `CLI`, `API`, `web coding`.
4. Optionally add OpenCC or an equivalent Simplified Chinese normalization pass after every backend.
