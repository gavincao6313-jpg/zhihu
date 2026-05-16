# Windows Runbook

## Daily Workflow

```bash
git pull --rebase
python zhihuTTS.py --status
python zhihuTTS.py
git status
git add .progress.json Markdowns/TTS_*.md runs/*.md
git commit -m "run: YYYY-MM-DD batch results"
git push
```

Run Owner owns `.progress.json`, generated `Markdowns/TTS_*.md`, and `runs/*.md`.
Do not edit `.py`, dependency, hook, or repo config files on Windows.

## Whisper Backend

Default safe mode:

```text
WHISPER_BACKEND=auto
WHISPER_BEAM_SIZE=1
WHISPER_WORD_TIMESTAMPS=0
WHISPER_CPU_THREADS=0
WHISPER_CPU_WORKERS=4
```

Optional whisper.cpp Vulkan mode:

```text
WHISPER_BACKEND=auto
WHISPER_CPP_EXE=D:\tools\whisper.cpp\whisper-cli.exe
WHISPER_CPP_MODEL=D:\tools\whisper.cpp\models\ggml-small-q5_0.bin
```

Use `WHISPER_BACKEND=whispercpp-vulkan` only when you want the run to fail if
the CLI backend is unavailable. In `auto`, the script falls back to CPU.

## Failure Playbooks

### Gemini 429 / Quota Exhausted

Stop the run if retries keep returning `RESOURCE_EXHAUSTED`. The quota counter
now tracks real Gemini requests, including continuation calls. Wait for quota
reset or switch to a billing-enabled project/provider that supports the needed
API surface.

### Gemini 503 / Transient Failure

Let the built-in retries run. If a video fails at `failed_stage=gemini`, retrying
later should reuse `cache/transcripts/` and `cache/keyframes/` instead of
rerunning ffmpeg and Whisper.

### C Drive Space Shortage

Temporary WAV files are written under `Videos/.tmp/`, not the system temp
directory. Clear `Videos/.tmp/` after a crashed run if files remain.

### Vulkan CLI Backend Unavailable

Check both files exist:

```text
D:\tools\whisper.cpp\whisper-cli.exe
D:\tools\whisper.cpp\models\ggml-small-q5_0.bin
```

If `WHISPER_BACKEND=auto`, the script should log the fallback reason and use CPU.
If `WHISPER_BACKEND=whispercpp-vulkan`, fix the paths or switch back to `auto`.

### CPU Fallback Verification

Look for log lines like:

```text
转写后端: cpu
CPU fallback reason: ...
```

### Markdown Generated but Progress Not Updated

Do not edit Python. Check the run log and `.progress.json`; if the Markdown is
complete, update `.progress.json` only if you can confirm the corresponding video
status and API call count.

### Progress Updated but Markdown Missing

The next run detects missing Markdown for videos marked done and schedules them
again. Keep the log evidence in the run report.
