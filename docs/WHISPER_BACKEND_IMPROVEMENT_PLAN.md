# Whisper Backend Improvement Plan

## Purpose

This document is the handoff from the Windows runner side to the Mac code-owner side.
It records the agreed improvements for the zhihu video-to-Markdown pipeline.

The current division of work still applies:

- Mac / Code Owner: modifies Python code, dependencies, hooks, and architecture docs.
- Windows / Run Owner: runs batches, checks logs, submits progress and generated Markdown.

## Current Assessment

The project goal is to convert long course videos in `Videos/` into detailed,
NotebookLM-ready Markdown files under `Markdowns/`.

The current architecture is workable:

1. `zhihuTTS_video.py` extracts keyframes with ffmpeg.
2. It transcribes audio with Whisper.
3. `zhihuTTS.py` sends transcript text plus keyframes to Gemini.
4. `.progress.json` tracks processing state and daily quota.

The main problem is not correctness, but production robustness and throughput.
The Windows machine is the batch runner, so the pipeline should optimize for:

- stable long-running execution,
- minimal reruns after failures,
- predictable disk usage,
- clear logs,
- safe fallback when GPU acceleration fails.

## Decision: Do Not Continue the Python Vulkan Binding Route

The previous attempt used `whisper-cpp-python + Vulkan`.
We should not continue relying on this path as the primary acceleration strategy.

Reasons:

- Windows + AMD + Python native build chain is fragile.
- It depends on CMake, Visual Studio Build Tools, Python ABI compatibility, and free C drive space.
- Failures are expensive for the Windows runner to diagnose.
- It is less suitable for the Mac-code / Windows-runner collaboration model.

The better route is:

1. Optimize the existing CPU path first.
2. Add an optional external `whisper.cpp` CLI backend for Vulkan acceleration.
3. Keep faster-whisper CPU as the reliable fallback.

## Phase 1: Optimize CPU Transcription

Current faster-whisper usage is expensive because it enables word-level timestamps:

```python
segments, info = model.transcribe(
    str(wav_path),
    language=language,
    beam_size=5,
    word_timestamps=True,
)
```

The main pipeline only uses segment-level fields:

```python
seg["start"], seg["end"], seg["text"]
```

So word-level timestamps should be disabled by default.

Recommended defaults:

```text
WHISPER_WORD_TIMESTAMPS=0
WHISPER_BEAM_SIZE=1
WHISPER_CPU_THREADS=0
WHISPER_CPU_WORKERS=4
```

Implementation sketch:

```python
beam_size = int(os.environ.get("WHISPER_BEAM_SIZE", "1"))
word_timestamps = os.environ.get("WHISPER_WORD_TIMESTAMPS", "0") == "1"

segments, info = model.transcribe(
    str(wav_path),
    language=language,
    beam_size=beam_size,
    word_timestamps=word_timestamps,
)
```

If `word_timestamps=False`, `_collect_segments()` should keep `words=[]`.

## Phase 2: Move Temporary WAV Files off C Drive

`tempfile.NamedTemporaryFile()` writes to the system temp directory by default.
On Windows this is usually the C drive, which has already been a bottleneck.

Temporary WAV files should be written inside the project workspace:

```text
Videos/.tmp/
```

Implementation sketch:

```python
TMP_DIR = Path(__file__).parent / "Videos" / ".tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)

with tempfile.NamedTemporaryFile(
    dir=TMP_DIR,
    suffix=".wav",
    prefix="zhihu_",
    delete=False,
) as f:
    wav_path = Path(f.name)
```

The file must still be removed in `finally`.

## Phase 3: Add whisper.cpp CLI Backend

Add a standalone CLI backend instead of using `whisper-cpp-python`.

Recommended Windows environment variables:

```text
WHISPER_BACKEND=whispercpp-vulkan
WHISPER_CPP_EXE=D:\tools\whisper.cpp\whisper-cli.exe
WHISPER_CPP_MODEL=D:\tools\whisper.cpp\models\ggml-small-q5_0.bin
```

The Python code should call the external CLI:

```bash
whisper-cli.exe -m model.bin -f audio.wav -l zh -oj
```

Then parse the generated JSON and convert it into the current transcript shape:

```python
{
    "segments": [
        {
            "start": float,
            "end": float,
            "text": str,
            "words": [],
        }
    ]
}
```

Recommended backend selection:

```text
WHISPER_BACKEND=auto
  1. If WHISPER_CPP_EXE and WHISPER_CPP_MODEL are configured, try whisper.cpp CLI first.
  2. If CLI fails, fall back to faster-whisper CPU.
  3. If WHISPER_BACKEND=whispercpp-vulkan is explicit, fail loudly when CLI fails.
```

Auto mode should catch broad backend exceptions and log the fallback reason.
Explicit Vulkan mode should not hide errors.

## Phase 4: Improve Gemini Input Alignment

The main flow currently sends keyframe image blobs without attaching frame metadata.
`build_gemini_payload()` already computes frame timestamps and events, but the main Gemini input path does not use that metadata.

Before each image part, insert a small text marker:

```text
Frame [00:12:34] type=slide diff=0.42
```

This helps Gemini align visual evidence with transcript time ranges.

## Phase 5: Track Real Gemini Calls

The current quota accounting increments after each video attempt.
This is not the same as actual Gemini API calls:

- local preprocessing failures can still increment quota,
- Gemini continuations can make multiple API calls for one video.

Recommended change:

- `process_video()` should return a structured result:

```python
{
    "success": bool,
    "failed_stage": "preprocess" | "gemini" | None,
    "gemini_calls": int,
    "backend_used": str,
    "fallback_reason": str | None,
}
```

- `.progress.json` should count real Gemini calls, not video attempts.

## Phase 6: Add Intermediate Cache

Failures after preprocessing currently force expensive reruns of ffmpeg and Whisper.

Recommended cache layout:

```text
cache/
  transcripts/<video_stem>.json
  keyframes/<video_stem>/manifest.json
  payloads/<video_stem>.json
```

Recommended status stages:

```text
new -> frames_done -> transcript_done -> gemini_done -> markdown_done
```

This allows the Windows runner to resume from the last successful stage.

## Phase 7: Add Windows Run Reports

Add a human-readable run report directory:

```text
runs/
  2026-05-16.md
```

Each report should include:

- start and end time,
- processed videos,
- success and failure count,
- backend used,
- fallback reason,
- Gemini calls,
- disk space,
- next recommended action.

`.progress.json` is for machines; `runs/*.md` is for humans and Codex handoff.

## Phase 8: Update Collaboration Rules for Two-Codex Workflow

Both the Mac side and the Windows side now have Codex. The collaboration model
should move from machine-based capability assumptions to responsibility-based
ownership.

Recommended roles:

| Role | Typical Machine | Responsibilities | Allowed Changes |
|---|---|---|---|
| Code Owner | Mac | Code changes, dependency changes, architecture changes, hooks, docs | `.py`, `requirements.txt`, `.gitignore`, `githooks/`, architecture docs |
| Run Owner | Windows | Batch execution, environment checks, log analysis, progress/result submission | `.progress.json`, generated `Markdowns/TTS_*.md`, `runs/*.md` |

The goal is not to prevent Windows Codex from being useful. The goal is to keep
production runs and code changes from stepping on each other.

Recommended `COLLABORATION.md` updates:

- Replace "Mac/Windows" as the only distinction with "Code Owner / Run Owner".
- Explicitly allow Windows / Run Owner to submit generated Markdown outputs.
- Keep Windows / Run Owner from editing `.py`, dependency, hook, and repo config files.
- Keep Mac / Code Owner from editing `.progress.json`.
- Require both sides to start with `git pull --rebase` or an equivalent clean sync.
- Require both sides to read `COLLABORATION.md` before beginning a Codex session.
- If Windows finds a code issue, it should submit a review note, issue, or docs handoff, not patch the code directly.

Recommended hook expansion:

- Windows / Run Owner should be blocked from committing:
  - `*.py`
  - `requirements.txt`
  - `.gitignore`
  - `.gitattributes`
  - `githooks/**`
- Mac / Code Owner should be blocked from committing:
  - `.progress.json`
- Everyone should be blocked from committing large runtime artifacts:
  - `Videos/*.mp4`
  - `*.wav`
  - `Videos/keyframes/**`
  - `Videos/.tmp/**`

Recommended commit message conventions:

```text
# Mac / Code Owner
fix: correct Gemini continuation accounting
perf: add whisper.cpp CLI backend
refactor: add preprocessing cache
docs: update collaboration rules

# Windows / Run Owner
progress: update processing state
data: add generated Markdown for RAG_04
run: 2026-05-16 batch report
```

## Phase 9: Add Windows Runbook

Add a `RUNBOOK.md` or `docs/WINDOWS_RUNBOOK.md` for the Windows runner.

It should include the normal daily workflow:

```bash
git pull --rebase
python zhihuTTS.py --status
python zhihuTTS.py
git status
git add .progress.json Markdowns/TTS_*.md runs/*.md
git commit -m "run: YYYY-MM-DD batch results"
git push
```

It should also include failure playbooks:

- Gemini 429 / quota exhausted.
- Gemini 503 / transient service failure.
- C drive space shortage.
- Vulkan CLI backend unavailable.
- CPU fallback verification.
- Markdown generated but `.progress.json` not updated.
- `.progress.json` updated but Markdown missing.

The runbook should make it possible for Windows Codex to continue safely without
guessing ownership boundaries.

## Suggested Implementation Order for Mac

1. Disable word timestamps by default and make beam size configurable.
2. Move temporary WAV files to `Videos/.tmp/`.
3. Add `_transcribe_whispercpp_cli()`.
4. Add backend selection and CPU fallback.
5. Log backend used, fallback reason, and transcription duration.
6. Add frame metadata markers before Gemini image parts.
7. Fix real Gemini call accounting.
8. Add intermediate cache and resumable statuses.
9. Add run report generation.
10. Update `COLLABORATION.md` for Code Owner / Run Owner responsibilities.
11. Expand `githooks/pre-commit` ownership checks.
12. Add `docs/WINDOWS_RUNBOOK.md` or `RUNBOOK.md`.

## Acceptance Criteria

- `python -m py_compile zhihuTTS.py zhihuTTS_video.py` passes.
- Without CLI configuration, CPU transcription still works.
- With invalid CLI configuration and `WHISPER_BACKEND=auto`, the script falls back to CPU.
- With invalid CLI configuration and `WHISPER_BACKEND=whispercpp-vulkan`, the script fails loudly.
- Temporary WAV files are created under `Videos/.tmp/`, not the C drive temp directory.
- Logs show the actual transcription backend.
- Gemini quota counts real Gemini requests.
- A failed Gemini call can be retried without repeating ffmpeg and Whisper work.
- `COLLABORATION.md` clearly states Code Owner / Run Owner boundaries.
- Git hooks block role-unsafe commits and large runtime artifacts.
- Windows runner has a runbook that covers normal runs and common failures.

## Windows Follow-up After Mac Implementation

Windows runner should prepare:

```text
D:\tools\whisper.cpp\whisper-cli.exe
D:\tools\whisper.cpp\models\ggml-small-q5_0.bin
```

Then benchmark one short or medium video with:

```text
WHISPER_BACKEND=auto
WHISPER_CPP_EXE=D:\tools\whisper.cpp\whisper-cli.exe
WHISPER_CPP_MODEL=D:\tools\whisper.cpp\models\ggml-small-q5_0.bin
```

If the CLI backend is unstable, leave `WHISPER_BACKEND=cpu` and continue batch processing with the optimized CPU path.
