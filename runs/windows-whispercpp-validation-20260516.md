# Windows whisper.cpp Validation - 2026-05-16

## Scope

- Pulled Mac-side changes with `git pull --rebase`.
- Validated `python zhihuTTS.py --status`.
- Validated `python zhihuTTS.py` with default safe mode plus local whisper.cpp CLI paths.

## Git Revision

- Before pull: `2680235`
- After pull: `ca840e9 perf: add whisper.cpp CLI backend`

## Environment

```text
WHISPER_BACKEND=auto
WHISPER_CPP_EXE=D:\tools\whisper.cpp\whisper-cli.exe
WHISPER_CPP_MODEL=D:\tools\whisper.cpp\models\ggml-small-q5_1.bin
WHISPER_BEAM_SIZE=1
WHISPER_WORD_TIMESTAMPS=0
WHISPER_CPU_THREADS=0
WHISPER_CPU_WORKERS=4
```

Note: the downloaded model is `ggml-small-q5_1.bin`, not the runbook example `ggml-small-q5_0.bin`.

## Results

- `whisper-cli.exe --help` runs successfully.
- `python zhihuTTS.py --status` runs successfully.
- First CPU fallback smoke run before whisper.cpp setup completed 3 videos and updated progress from 35/63 to 38/63.
- whisper.cpp validation run used `whispercpp-vulkan`:
  - Video: `部署交付_01_【David】智能算力那点事儿`
  - Keyframes: 360
  - Transcript segments: 2507
  - Transcript chars: 87130
  - Backend log: `转写后端: whispercpp-vulkan`
  - Transcription time: 2217.28s
- The first whisper.cpp validation command timed out during Gemini send after preprocessing completed. Cache artifacts were created under:
  - `cache/keyframes/部署交付_01_【David】智能算力那点事儿/`
  - `cache/transcripts/部署交付_01_【David】智能算力那点事儿.json`
  - `cache/payloads/部署交付_01_【David】智能算力那点事儿.json`
- Retry verified cache reuse:
  - Log line: `命中预处理缓存: 360 张关键帧`
  - No repeat ffmpeg/Whisper preprocessing for that video.
  - Gemini completed and wrote `Markdowns/TTS_0516_部署交付_01_【David】智能算力那点事儿.md`.
  - Progress updated to 39/63, quota 11/20.

## Generated Outputs

- `Markdowns/TTS_0516_产品设计运营_08_【李智勇】全AI驱动的商业体与无人公司的案例与实践.md`
- `Markdowns/TTS_0516_多模态_01_【吴桂林】数字分身应用及技术介绍.md`
- `Markdowns/TTS_0516_多模态_02_【王宇泽】数字人揭秘：从技术原理到商业落地的全景解析.md`
- `Markdowns/TTS_0516_部署交付_01_【David】智能算力那点事儿.md`
- `.progress.json`

## Issues / Notes

- PowerShell profile still emits execution-policy noise on every shell command.
- Git also reports permission warnings for `C:\Users\Admin\.config\git\ignore`.
- `zhihuTTS.log` was modified by the run, but it is not part of the Windows Runbook commit set.
- `runs/windows-verify-20260516-161025.*.log` are empty because the initial background launch command exited immediately.
